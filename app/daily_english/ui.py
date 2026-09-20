from __future__ import annotations

import sys
import webbrowser
from collections import deque
from pathlib import Path
from threading import Event

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QComboBox, QCheckBox, QHeaderView, QProgressBar, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .database import LibraryDatabase
from .engine import EngineRunner
from .models import DownloadStatus, Project, ProjectStatus, Resource
from .model_cache import (
    SUPPORTED_MODELS, format_size, hub_cache_path, model_cache_info,
    remove_cached_model, resolve_faster_whisper_model,
)
from .pipeline import CaptionPipeline
from .processes import TaskCancelled, ensure_not_cancelled
from .providers import BilibiliProvider, TedProvider, YouTubeProvider, bilibili_search_url
from .downloader import DownloadResult, WeChatChannelsDownloader, YtDlpDownloader, detect_platform
from .settings import (
    bool_setting, last_directory, load_settings, remember_last_path, save_settings,
    set_setting,
)


class SelectableLabelFilter(QObject):
    """Make informational labels, including message-box labels, selectable and copyable."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QLabel) and event.type() == QEvent.Type.Show:
            watched.setTextInteractionFlags(
                watched.textInteractionFlags()
                | Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            watched.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        return super().eventFilter(watched, event)


class CopyableListWidget(QListWidget):
    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            items = self.selectedItems()
            if items:
                QApplication.clipboard().setText("\n".join(item.text() for item in items))
                event.accept()
                return
        super().keyPressEvent(event)


class CopyableTableWidget(QTableWidget):
    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            indexes = self.selectedIndexes()
            if indexes:
                rows = range(min(index.row() for index in indexes), max(index.row() for index in indexes) + 1)
                columns = range(min(index.column() for index in indexes), max(index.column() for index in indexes) + 1)
                lines = []
                for row in rows:
                    values = []
                    for column in columns:
                        item = self.item(row, column)
                        widget = self.cellWidget(row, column)
                        values.append(item.text() if item else (widget.text() if isinstance(widget, QProgressBar) else ""))
                    lines.append("\t".join(values))
                QApplication.clipboard().setText("\n".join(lines))
                event.accept()
                return
        super().keyPressEvent(event)


class SearchTab(QWidget):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__()
        self.main = parent
        self.resources: list[Resource] = []
        self.workers: dict[DownloadWorker, int] = {}
        layout = QVBoxLayout(self)
        form = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("输入标题、关键词或 YouTube/B站/视频号链接")
        self.source = QLineEdit()
        self.source.setPlaceholderText("YouTube API Key（可选）")
        self.source.setEchoMode(QLineEdit.EchoMode.Password)
        self.search_button = QPushButton("搜索")
        self.search_button.clicked.connect(self.search)
        form.addWidget(self.query, 2); form.addWidget(self.source, 1); form.addWidget(self.search_button)
        layout.addLayout(form)
        self.results = CopyableListWidget()
        self.results.itemDoubleClicked.connect(self.open_resource)
        self.results.currentItemChanged.connect(self.show_resource_details)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("选择搜索结果后，可在这里查看并复制来源信息。")
        results_splitter = QSplitter(Qt.Orientation.Vertical)
        results_splitter.addWidget(self.results)
        results_splitter.addWidget(self.details)
        results_splitter.setStretchFactor(0, 3)
        results_splitter.setStretchFactor(1, 1)
        layout.addWidget(results_splitter, 1)
        actions = QHBoxLayout()
        self.audio_button = QPushButton("下载音频 MP3")
        self.video_button = QPushButton("下载视频 MP4")
        self.audio_button.clicked.connect(lambda: self.download_selected("audio"))
        self.video_button.clicked.connect(lambda: self.download_selected("video"))
        actions.addWidget(self.audio_button); actions.addWidget(self.video_button)
        self.progress = QLabel("")
        self.progress.setWordWrap(True)
        actions.addWidget(self.progress, 1); layout.addLayout(actions)
        hint = QLabel("双击结果打开来源页面。线上结果仅用于发现，媒体请在获得授权后导入本地文件。")
        hint.setWordWrap(True); layout.addWidget(hint)

    def search(self) -> None:
        query = self.query.text().strip()
        if not query:
            QMessageBox.information(self, "需要关键词", "请输入文章标题或关键词。")
            return
        settings = load_settings()
        key = self.source.text().strip() or settings.get("youtube_api_key", "")
        if self.source.text().strip():
            settings["youtube_api_key"] = self.source.text().strip(); save_settings(settings)
        errors = []
        try:
            if detect_platform(query):
                platform = detect_platform(query) or "未知"
                if platform == "WeChat Channels":
                    info = WeChatChannelsDownloader().inspect(query)
                    self.resources = [Resource(
                        provider=platform, title=info.title, author=info.author, url=query,
                        download_url=query, language="中文",
                        license_note="匿名解析公开信息；仅当微信官方响应提供媒体流时才允许下载。",
                    )]
                else:
                    self.resources = [Resource(provider=platform, title=query, url=query, download_url=query)]
            else:
                self.resources = TedProvider().search(query)
                try:
                    self.resources += BilibiliProvider().search(query)
                except Exception as error:
                    errors.append(f"B 站：{error}")
                if key:
                    try:
                        self.resources += YouTubeProvider(key).search(query)
                    except Exception as error:
                        errors.append(f"YouTube：{error}")
        except Exception as error:
            errors.append(f"TED：{error}")
        if errors and not self.resources:
            QMessageBox.warning(self, "搜索失败", "\n".join(errors))
            return
        self.results.clear()
        for resource in self.resources:
            item = QListWidgetItem(f"[{resource.provider}] {resource.title}")
            item.setToolTip(f"{resource.author}\n{resource.url}\n{resource.license_note}")
            item.setData(Qt.ItemDataRole.UserRole, resource)
            self.results.addItem(item)
        if errors:
            self.progress.setText("；".join(errors) + f"；可打开 B 站搜索：{bilibili_search_url(query)}")

    def show_resource_details(
        self, item: QListWidgetItem | None, _previous: QListWidgetItem | None = None,
    ) -> None:
        if item is None:
            self.details.clear()
            return
        resource: Resource = item.data(Qt.ItemDataRole.UserRole)
        self.details.setPlainText(
            f"标题：{resource.title}\n"
            f"作者：{resource.author or '未知'}\n"
            f"平台：{resource.provider}\n"
            f"链接：{resource.url}\n"
            f"说明：{resource.license_note}"
        )

    def download_selected(self, media_kind: str) -> None:
        item = self.results.currentItem()
        if item is None:
            QMessageBox.information(self, "未选择资源", "请先选择一个搜索结果或直接粘贴链接搜索。")
            return
        resource: Resource = item.data(Qt.ItemDataRole.UserRole)
        destination = QFileDialog.getExistingDirectory(
            self, "选择下载目录", last_directory("download"),
        )
        if not destination:
            return
        remember_last_path(destination, "download")
        worker = DownloadWorker(resource.download_url or resource.url, destination, media_kind)
        task_id = self.main.task_center.add_task("下载", resource.title)
        self.workers[worker] = task_id
        worker.progress.connect(lambda percent, text, current=task_id: self._download_progress(current, percent, text))
        worker.completed.connect(lambda result, current=worker: self.download_completed(current, result))
        worker.failed.connect(lambda message, current=worker: self.download_failed(current, message))
        worker.cancelled.connect(lambda current=worker: self.download_cancelled(current))
        worker.finished.connect(lambda current=worker: self._download_finished(current))
        worker.start()
        self.progress.setText(f"下载任务已启动；当前并行下载 {len(self.workers)} 个")

    def _download_progress(self, task_id: int, percent: float, text: str) -> None:
        self.progress.setText(f"{percent:.1f}% {text}")
        self.main.task_center.update_task(task_id, "下载中", percent, text)

    def download_completed(self, worker: "DownloadWorker", result: DownloadResult) -> None:
        task_id = self.workers[worker]
        self.main.task_center.update_task(task_id, "已完成", 100.0, str(result.path))
        self.progress.setText("下载完成")
        source_language = "zh-cn" if result.platform in {"Bilibili", "WeChat Channels"} else "auto"
        project = Project(None, result.title, result.author, result.platform, result.url, str(result.path))
        project.source_language = source_language; project.download_status = DownloadStatus.DOWNLOADED; project.download_format = result.media_kind
        project.target_language = "en" if source_language.startswith("zh") else "zh"
        project.subtitle_order = "source_first"
        self.main.current_project = self.main.database.save_project(project)
        self.main.refresh_library()
        self.main.show_status(f"下载完成并已加入资料库：{result.path}", 12000)

    def download_failed(self, worker: "DownloadWorker", message: str) -> None:
        task_id = self.workers[worker]
        self.main.task_center.update_task(task_id, "失败", 0.0, message)
        self.progress.setText("下载失败")
        QMessageBox.warning(self, "下载失败", message)

    def download_cancelled(self, worker: "DownloadWorker") -> None:
        task_id = self.workers[worker]
        self.main.task_center.update_task(task_id, "已取消", 0.0, "下载任务已取消")
        self.progress.setText("下载已取消")

    def cancel_task(self, task_id: int) -> bool:
        for worker, current_task_id in self.workers.items():
            if current_task_id == task_id:
                worker.cancel()
                self.main.task_center.update_task(task_id, "正在取消", -1.0, "等待下载安全停止…")
                return True
        return False

    def _download_finished(self, worker: "DownloadWorker") -> None:
        self.workers.pop(worker, None)
        worker.deleteLater()

    @staticmethod
    def open_resource(item: QListWidgetItem) -> None:
        resource: Resource = item.data(Qt.ItemDataRole.UserRole)
        webbrowser.open(resource.url)


class DownloadWorker(QThread):
    progress = Signal(float, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, url: str, destination: str, media_kind: str) -> None:
        super().__init__(); self.url = url; self.destination = destination; self.media_kind = media_kind
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _report(self, percent: float, message: str) -> None:
        ensure_not_cancelled(self._cancel_event.is_set)
        self.progress.emit(percent, message)

    def run(self) -> None:
        try:
            result = YtDlpDownloader().download(self.url, self.destination, self.media_kind, self._report)
            ensure_not_cancelled(self._cancel_event.is_set)
            self.completed.emit(result)
        except TaskCancelled:
            self.cancelled.emit()
        except Exception as error:
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(str(error))


class ProcessWorker(QThread):
    progress = Signal(float, str)
    completed = Signal(object)
    failed = Signal(object, str)
    cancelled = Signal(object)

    def __init__(self, project: Project, model_name: str) -> None:
        super().__init__()
        self.project = project
        self.model_name = model_name
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _report(self, percent: float, message: str) -> None:
        ensure_not_cancelled(self._cancel_event.is_set)
        self.progress.emit(percent, message)

    def run(self) -> None:
        try:
            pipeline = CaptionPipeline()
            if not self.project.captions:
                pipeline.transcribe(
                    self.project, self.model_name, self._report,
                    cancel_requested=self._cancel_event.is_set,
                )
            else:
                self._report(85.0, "已有原文字幕，跳过语音转写")
            pipeline.translate_missing(
                self.project, self._report, cancel_requested=self._cancel_event.is_set,
            )
            self._report(100.0, "处理完成")
            self.completed.emit(self.project)
        except TaskCancelled:
            self.cancelled.emit(self.project)
        except Exception as error:
            self.failed.emit(self.project, str(error))


class ExportWorker(QThread):
    progress = Signal(float, str)
    completed = Signal(object, object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, project: Project, destination: str) -> None:
        super().__init__()
        self.project = project
        self.destination = destination
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _report(self, percent: float, message: str) -> None:
        ensure_not_cancelled(self._cancel_event.is_set)
        self.progress.emit(percent, message)

    def run(self) -> None:
        try:
            package = CaptionPipeline().export_package(
                self.project, self.destination, create_zip=True,
                progress=self._report, cancel_requested=self._cancel_event.is_set,
            )
            ensure_not_cancelled(self._cancel_event.is_set)
            self.completed.emit(self.project, package)
        except TaskCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))


class ModelDownloadWorker(QThread):
    progress = Signal(float, str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, model_name: str, cache_root: Path) -> None:
        super().__init__()
        self.model_name = model_name
        self.cache_root = cache_root
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _report(self, percent: float, message: str) -> None:
        ensure_not_cancelled(self._cancel_event.is_set)
        self.progress.emit(percent, message)

    def run(self) -> None:
        try:
            resolve_faster_whisper_model(self.model_name, self.cache_root, self._report)
            ensure_not_cancelled(self._cancel_event.is_set)
            self.completed.emit(self.model_name)
        except TaskCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))


class TaskCenterTab(QWidget):
    concurrency_changed = Signal(int)
    cancel_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.next_task_id = 1
        self.rows: dict[int, int] = {}
        layout = QVBoxLayout(self)
        options = QHBoxLayout()
        options.addWidget(QLabel("最大并发转写任务"))
        self.processing_concurrency = QComboBox()
        self.processing_concurrency.addItem("1（推荐，适合 medium/large-v3）", 1)
        self.processing_concurrency.addItem("2（需要更多内存/显存）", 2)
        self.processing_concurrency.currentIndexChanged.connect(
            lambda: self.concurrency_changed.emit(self.max_processing_workers())
        )
        options.addWidget(self.processing_concurrency)
        self.cancel_button = QPushButton("取消所选任务")
        self.cancel_button.clicked.connect(self.cancel_selected_tasks)
        options.addWidget(self.cancel_button)
        options.addStretch(1)
        layout.addLayout(options)
        self.table = CopyableTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["类型", "项目", "状态", "进度", "详情"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        hint = QLabel("下载可同时进行；转写默认串行。内存充足时可切换为 2 个并发任务。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def max_processing_workers(self) -> int:
        return int(self.processing_concurrency.currentData())

    def cancel_selected_tasks(self) -> None:
        selected_rows = {index.row() for index in self.table.selectedIndexes()}
        for task_id, row in self.rows.items():
            if row in selected_rows:
                self.cancel_requested.emit(task_id)

    def add_task(self, kind: str, title: str) -> int:
        task_id = self.next_task_id
        self.next_task_id += 1
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.rows[task_id] = row
        for column, value in enumerate((kind, title, "排队中")):
            self.table.setItem(row, column, QTableWidgetItem(value))
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setFormat("0.0%")
        self.table.setCellWidget(row, 3, bar)
        self.table.setItem(row, 4, QTableWidgetItem(""))
        self.table.resizeRowToContents(row)
        return task_id

    def update_task(self, task_id: int, status: str, percent: float, message: str) -> None:
        row = self.rows.get(task_id)
        if row is None:
            return
        self.table.item(row, 2).setText(status)
        self.table.item(row, 4).setText(message)
        bar = self.table.cellWidget(row, 3)
        if not isinstance(bar, QProgressBar):
            return
        if percent < 0:
            bar.setRange(0, 0)
            bar.setFormat("处理中…")
        else:
            bar.setRange(0, 1000)
            bar.setValue(round(min(100.0, percent) * 10))
            bar.setFormat(f"{min(100.0, percent):.1f}%")
        self.table.resizeRowToContents(row)


class ModelManagerTab(QWidget):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__()
        self.main = parent
        self.cache_root = EngineRunner().cache_root
        self.worker: ModelDownloadWorker | None = None
        self.task_id: int | None = None
        layout = QVBoxLayout(self)
        description = QLabel("模型只需下载一次。这里可以查看本地状态、磁盘占用，或主动下载和删除模型。")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.table = CopyableTableWidget(len(SUPPORTED_MODELS), 3)
        self.table.setHorizontalHeaderLabels(["模型", "本地状态", "磁盘占用"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for row, model_name in enumerate(SUPPORTED_MODELS):
            self.table.setItem(row, 0, QTableWidgetItem(model_name))
            self.table.setItem(row, 1, QTableWidgetItem("检查中…"))
            self.table.setItem(row, 2, QTableWidgetItem("—"))
        self.table.selectRow(0)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.download_button = QPushButton("下载所选模型")
        self.remove_button = QPushButton("删除所选模型")
        refresh_button = QPushButton("刷新状态")
        open_button = QPushButton("打开缓存目录")
        self.download_button.clicked.connect(self.download_selected)
        self.remove_button.clicked.connect(self.remove_selected)
        refresh_button.clicked.connect(self.refresh)
        open_button.clicked.connect(self.open_cache_directory)
        actions.addWidget(self.download_button)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        actions.addWidget(refresh_button)
        actions.addWidget(open_button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def selected_model(self) -> str | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.text() if item else None

    def refresh(self) -> None:
        total_size = 0
        for row, model_name in enumerate(SUPPORTED_MODELS):
            info = model_cache_info(model_name, self.cache_root)
            total_size += info.size_bytes
            self.table.item(row, 1).setText("已安装" if info.installed else "未安装")
            self.table.item(row, 2).setText(format_size(info.size_bytes) if info.installed else "—")
            self.table.item(row, 1).setToolTip(str(info.path or ""))
        self.status.setText(
            f"缓存目录：{hub_cache_path(self.cache_root)}\n三个模型合计：{format_size(total_size)}"
        )

    def download_selected(self) -> None:
        model_name = self.selected_model()
        if model_name is None:
            return
        if self.worker is not None:
            QMessageBox.information(self, "模型任务进行中", "请等待当前模型任务结束。")
            return
        if model_cache_info(model_name, self.cache_root).installed:
            QMessageBox.information(self, "模型已安装", f"{model_name} 已在本地缓存中，无需重复下载。")
            return
        worker = ModelDownloadWorker(model_name, self.cache_root)
        task_id = self.main.task_center.add_task("模型", model_name)
        self.worker = worker
        self.task_id = task_id
        self.download_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        worker.progress.connect(lambda percent, message: self._download_progress(task_id, percent, message))
        worker.completed.connect(self._download_completed)
        worker.failed.connect(self._download_failed)
        worker.cancelled.connect(self._download_cancelled)
        worker.finished.connect(self._download_finished)
        worker.start()

    def _download_progress(self, task_id: int, percent: float, message: str) -> None:
        self.status.setText(message)
        self.main.task_center.update_task(task_id, "下载中", percent, message)

    def _download_completed(self, model_name: str) -> None:
        if self.task_id is not None:
            self.main.task_center.update_task(self.task_id, "已完成", 100.0, f"{model_name} 已缓存")
        self.refresh()
        self.main.show_status(f"模型 {model_name} 下载完成", 10000)

    def _download_failed(self, message: str) -> None:
        if self.task_id is not None:
            self.main.task_center.update_task(self.task_id, "失败", 0.0, message)
        self.status.setText(message)
        QMessageBox.warning(self, "模型下载失败", message)

    def _download_cancelled(self) -> None:
        if self.task_id is not None:
            self.main.task_center.update_task(self.task_id, "已取消", 0.0, "模型任务已取消")
        self.status.setText("模型任务已取消")

    def _download_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self.task_id = None
        self.download_button.setEnabled(True)
        self.remove_button.setEnabled(True)

    def remove_selected(self) -> None:
        model_name = self.selected_model()
        if model_name is None:
            return
        if self.worker is not None or self.main.import_tab.active_workers or self.main.import_tab.pending_workers:
            QMessageBox.information(self, "模型正在使用", "请先等待模型下载或字幕任务结束。")
            return
        info = model_cache_info(model_name, self.cache_root)
        if not info.installed:
            QMessageBox.information(self, "模型未安装", f"{model_name} 当前没有本地缓存。")
            return
        answer = QMessageBox.question(
            self, "删除模型",
            f"确定删除 {model_name} 的本地缓存（{format_size(info.size_bytes)}）吗？\n以后使用时需要重新下载。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            remove_cached_model(model_name, self.cache_root)
            self.refresh()
            self.main.show_status(f"已删除模型 {model_name} 的本地缓存", 10000)
        except OSError as error:
            QMessageBox.warning(self, "删除失败", str(error))

    def open_cache_directory(self) -> None:
        directory = hub_cache_path(self.cache_root)
        directory.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve()))):
            self.main.show_status(f"无法打开模型缓存目录：{directory}", 8000)

    def cancel_task(self, task_id: int) -> bool:
        if self.worker is not None and self.task_id == task_id:
            self.worker.cancel()
            self.main.task_center.update_task(task_id, "正在取消", -1.0, "下载结束后将停止模型任务…")
            return True
        return False


class ImportTab(QWidget):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(); self.main = parent
        self.pending_workers: deque[tuple[ProcessWorker, int]] = deque()
        self.active_workers: dict[ProcessWorker, int] = {}
        self.queued_project_ids: set[int] = set()
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.title = QLineEdit(); self.author = QLineEdit(); self.url = QLineEdit()
        self.media = QLineEdit(); self.reference = QLineEdit(); self.subtitle = QLineEdit()
        self._suggested_title = ""
        self._title_edited_by_user = False
        self.title.setPlaceholderText("选择媒体后自动使用文件名，可手动修改")
        self.title.textEdited.connect(self._mark_title_edited)
        self.media.editingFinished.connect(self._suggest_title_from_media_field)
        self.source_language = QComboBox(); self.source_language.addItem("自动检测", "auto"); self.source_language.addItem("中文", "zh-cn"); self.source_language.addItem("英语", "en")
        self.target_language = QComboBox(); self.target_language.addItem("英语", "en"); self.target_language.addItem("中文", "zh")
        self.source_language.currentIndexChanged.connect(self._update_target_language)
        self.model_name = QComboBox(); self.model_name.addItems(["small", "medium", "large-v3"])
        self.alignment = QCheckBox("启用 WhisperX/词级对齐（sidecar 可用时）")
        self.engine_status = QLabel()
        self.refresh_engine_status()
        self.engine_status.setWordWrap(True)
        form.addRow("标题", self.title); form.addRow("作者", self.author); form.addRow("来源链接", self.url)
        form.addRow("源语言", self.source_language); form.addRow("目标语言", self.target_language)
        form.addRow("识别模型", self.model_name); form.addRow("对齐", self.alignment); form.addRow("处理引擎", self.engine_status)
        form.addRow("本地媒体", self._picker(self.media, "媒体文件", "音频或视频 (*.*)", "media"))
        form.addRow("参考文稿", self._picker(self.reference, "参考文稿", "文稿 (*.txt *.docx *.pdf)", "reference"))
        form.addRow("已有字幕", self._picker(self.subtitle, "SRT 字幕", "字幕 (*.srt)", "subtitle"))
        self.process_progress = QProgressBar(); self.process_progress.setRange(0, 1000); self.process_progress.setValue(0)
        self.process_message = QLabel("尚未开始")
        self.process_message.setWordWrap(True)
        form.addRow("当前进度", self.process_progress); form.addRow("处理状态", self.process_message)
        buttons = QHBoxLayout(); import_button = QPushButton("建立项目")
        import_button.clicked.connect(self.create_project); process_button = QPushButton("加入处理队列")
        process_button.clicked.connect(self.process_project); buttons.addWidget(import_button); buttons.addWidget(process_button)
        form.addRow(buttons)
        self.main.task_center.concurrency_changed.connect(lambda _count: self._start_pending())

    def refresh_engine_status(self) -> None:
        status = EngineRunner().status()
        self.engine_status.setText(status.message)
        self.alignment.setEnabled(status.available)
        if status.available:
            self.alignment.setToolTip("使用 pyVideoTrans sidecar 执行 WhisperX/词级对齐。")
        else:
            self.alignment.setChecked(False)
            self.alignment.setToolTip("安装可选 pyVideoTrans sidecar 后才能启用 WhisperX/词级对齐。")

    def _update_target_language(self) -> None:
        source = self.source_language.currentData()
        target = "en" if source == "zh-cn" else "zh"
        index = self.target_language.findData(target)
        if index >= 0:
            self.target_language.setCurrentIndex(index)

    def _mark_title_edited(self, _text: str) -> None:
        self._title_edited_by_user = True

    def _suggest_title_from_media_field(self) -> None:
        media_path = self.media.text().strip()
        if not media_path:
            return
        suggested_title = Path(media_path).stem.strip()
        if not suggested_title:
            return
        current_title = self.title.text().strip()
        if self._title_edited_by_user and current_title != self._suggested_title:
            return
        self._suggested_title = suggested_title
        self._title_edited_by_user = False
        self.title.setText(suggested_title)

    def _picker(self, field: QLineEdit, title: str, filter_text: str, purpose: str) -> QWidget:
        widget = QWidget(); row = QHBoxLayout(widget); row.setContentsMargins(0, 0, 0, 0); row.addWidget(field)
        button = QPushButton("选择"); button.clicked.connect(lambda: self.pick(field, title, filter_text, purpose)); row.addWidget(button); return widget

    def pick(self, field: QLineEdit, title: str, filter_text: str, purpose: str) -> None:
        current = Path(field.text().strip()) if field.text().strip() else None
        initial = str(current.parent if current and current.is_file() else last_directory(purpose))
        path, _ = QFileDialog.getOpenFileName(self, title, initial, filter_text)
        if path:
            field.setText(path)
            if purpose == "media":
                self._suggest_title_from_media_field()
            remember_last_path(path, purpose)

    def create_project(self) -> None:
        if not self.title.text().strip() or not self.media.text().strip():
            QMessageBox.information(self, "信息不完整", "标题和本地媒体是必填项。"); return
        project = Project(None, self.title.text().strip(), self.author.text().strip(), "本地导入", self.url.text().strip(), self.media.text().strip(), self.reference.text().strip())
        project.source_language = self.source_language.currentData()
        project.target_language = self.target_language.currentData()
        project.subtitle_order = "source_first"
        project.recognition_engine = "pyVideoTrans" if EngineRunner().status().available else "faster-whisper"
        project.alignment_enabled = self.alignment.isChecked()
        if self.subtitle.text().strip():
            try: CaptionPipeline().import_srt(project, self.subtitle.text().strip())
            except Exception as error: QMessageBox.warning(self, "字幕导入失败", str(error)); return
        self.main.current_project = self.main.database.save_project(project)
        self.main.refresh_library(); QMessageBox.information(self, "已建立", "项目已加入本地资料库。")

    def process_project(self) -> None:
        project = self.main.current_project
        if project is None: QMessageBox.information(self, "没有项目", "请先建立项目或从资料库打开项目。"); return
        if project.id is None:
            QMessageBox.information(self, "项目未保存", "请先建立并保存项目。")
            return
        if project.id in self.queued_project_ids:
            QMessageBox.information(self, "任务已存在", "该项目已经在排队或处理中。")
            return
        project = self.main.database.get_project(project.id)
        project.status = ProjectStatus.PROCESSING
        project.error = ""
        project = self.main.database.save_project(project)
        worker = ProcessWorker(project, self.model_name.currentText())
        task_id = self.main.task_center.add_task("字幕", project.title)
        worker.progress.connect(lambda percent, text, current=task_id: self._process_progress(current, percent, text))
        worker.completed.connect(lambda result, current=worker: self._process_completed(current, result))
        worker.failed.connect(lambda result, message, current=worker: self._process_failed(current, result, message))
        worker.cancelled.connect(lambda result, current=worker: self._process_cancelled(current, result))
        worker.finished.connect(lambda current=worker: self._process_finished(current))
        self.pending_workers.append((worker, task_id))
        self.queued_project_ids.add(project.id)
        self.main.refresh_library()
        self.process_message.setText("任务已加入队列")
        self._start_pending()

    def cancel_task(self, task_id: int) -> bool:
        remaining: deque[tuple[ProcessWorker, int]] = deque()
        cancelled_worker: ProcessWorker | None = None
        while self.pending_workers:
            worker, current_task_id = self.pending_workers.popleft()
            if current_task_id == task_id:
                cancelled_worker = worker
            else:
                remaining.append((worker, current_task_id))
        self.pending_workers = remaining
        if cancelled_worker is not None:
            project = cancelled_worker.project
            project.status = ProjectStatus.CANCELLED
            project.error = "任务在开始前被取消。"
            self.main.database.save_project(project)
            if project.id is not None:
                self.queued_project_ids.discard(project.id)
            self.main.task_center.update_task(task_id, "已取消", 0.0, project.error)
            cancelled_worker.deleteLater()
            self.main.refresh_library()
            return True
        for worker, current_task_id in self.active_workers.items():
            if current_task_id == task_id:
                worker.cancel()
                self.main.task_center.update_task(task_id, "正在取消", -1.0, "等待当前步骤安全停止…")
                return True
        return False

    def _start_pending(self) -> None:
        limit = self.main.task_center.max_processing_workers()
        while self.pending_workers and len(self.active_workers) < limit:
            worker, task_id = self.pending_workers.popleft()
            self.active_workers[worker] = task_id
            self.main.task_center.update_task(task_id, "处理中", 0.0, f"正在加载 {worker.model_name} 模型")
            worker.start()

    def _process_progress(self, task_id: int, percent: float, text: str) -> None:
        self.main.task_center.update_task(task_id, "处理中", percent, text)
        self.process_message.setText(text)
        if percent < 0:
            self.process_progress.setRange(0, 0)
        else:
            self.process_progress.setRange(0, 1000)
            self.process_progress.setValue(round(min(100.0, percent) * 10))
            self.process_progress.setFormat(f"{min(100.0, percent):.1f}%")

    def _process_completed(self, worker: ProcessWorker, project: Project) -> None:
        project.status = ProjectStatus.REVIEW
        project.error = ""
        saved = self.main.database.save_project(project)
        task_id = self.active_workers[worker]
        self.main.task_center.update_task(task_id, "已完成", 100.0, "可在字幕预览中检查和导出")
        self.process_progress.setRange(0, 1000); self.process_progress.setValue(1000); self.process_progress.setFormat("100.0%")
        self.process_message.setText(f"{project.title} 处理完成")
        if self.main.current_project and self.main.current_project.id == saved.id:
            self.main.current_project = saved
            self.main.refresh_editor()
        self.main.refresh_library()
        self.main.show_status(f"字幕任务完成：{project.title}", 12000)

    def _process_failed(self, worker: ProcessWorker, project: Project, message: str) -> None:
        project.status = ProjectStatus.FAILED
        project.error = message
        self.main.database.save_project(project)
        task_id = self.active_workers[worker]
        self.main.task_center.update_task(task_id, "失败", 0.0, message)
        self.process_progress.setRange(0, 1000); self.process_progress.setValue(0)
        self.process_message.setText(f"处理失败：{message}")
        self.main.refresh_library()

    def _process_cancelled(self, worker: ProcessWorker, project: Project) -> None:
        project.status = ProjectStatus.CANCELLED
        project.error = "任务已由用户取消。"
        self.main.database.save_project(project)
        task_id = self.active_workers[worker]
        self.main.task_center.update_task(task_id, "已取消", 0.0, project.error)
        self.process_progress.setRange(0, 1000)
        self.process_progress.setValue(0)
        self.process_message.setText(project.error)
        self.main.refresh_library()

    def load_project(self, project: Project) -> None:
        self.title.setText(project.title)
        self._suggested_title = ""
        self._title_edited_by_user = True
        self.author.setText(project.author)
        self.url.setText(project.source_url)
        self.media.setText(project.media_path)
        self.reference.setText(project.reference_path)
        source_index = self.source_language.findData(project.source_language)
        if source_index >= 0:
            self.source_language.setCurrentIndex(source_index)
        target_index = self.target_language.findData(project.target_language)
        if target_index >= 0:
            self.target_language.setCurrentIndex(target_index)
        self.alignment.setChecked(project.alignment_enabled)
        self.process_message.setText(project.error or f"已载入项目：{project.title}")

    def _process_finished(self, worker: ProcessWorker) -> None:
        self.active_workers.pop(worker, None)
        if worker.project.id is not None:
            self.queued_project_ids.discard(worker.project.id)
        worker.deleteLater()
        self._start_pending()


class EditorTab(QWidget):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(); self.main = parent
        self.export_worker: ExportWorker | None = None
        self.export_task_id: int | None = None
        layout = QVBoxLayout(self); self.table = CopyableTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["开始(s)", "结束(s)", "原文", "译文"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        buttons = QHBoxLayout(); save = QPushButton("保存修改"); save.clicked.connect(lambda: self.save())
        self.export_button = QPushButton("导出 MP3 + SRT"); self.export_button.clicked.connect(self.export)
        self.open_export_folder = QCheckBox("导出完成后打开文件夹")
        self.open_export_folder.setChecked(bool_setting("open_export_folder_after_export", True))
        self.open_export_folder.toggled.connect(
            lambda checked: set_setting("open_export_folder_after_export", checked)
        )
        buttons.addWidget(self.open_export_folder)
        buttons.addStretch(1)
        buttons.addWidget(save); buttons.addWidget(self.export_button); layout.addLayout(buttons)
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 1000)
        self.export_progress.setValue(0)
        self.export_progress.setVisible(False)
        layout.addWidget(self.export_progress)

    def load(self, project: Project) -> None:
        self.table.setRowCount(len(project.captions))
        for row, caption in enumerate(project.captions):
            for column, value in enumerate((f"{caption.start:.3f}", f"{caption.end:.3f}", caption.source_text, caption.translated_text)):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeRowsToContents()

    def save(self, show_message: bool = True) -> bool:
        project = self.main.current_project
        if project is None: return False
        try:
            for row, caption in enumerate(project.captions):
                caption.start = float(self.table.item(row, 0).text()); caption.end = float(self.table.item(row, 1).text())
                caption.source_text = self.table.item(row, 2).text(); caption.translated_text = self.table.item(row, 3).text()
            self.main.current_project = self.main.database.save_project(project)
            if show_message:
                QMessageBox.information(self, "已保存", "字幕修改已保存。")
            return True
        except Exception as error:
            QMessageBox.warning(self, "保存失败", str(error))
            return False

    def export(self) -> None:
        if self.export_worker is not None:
            QMessageBox.information(self, "正在导出", "当前导出任务尚未完成。")
            return
        if not self.save(show_message=False):
            return
        project = self.main.current_project
        if project is None: return
        destination = QFileDialog.getExistingDirectory(
            self, "选择导出目录", last_directory("export"),
        )
        if not destination: return
        remember_last_path(destination, "export")
        worker = ExportWorker(project, destination)
        task_id = self.main.task_center.add_task("导出", project.title)
        self.export_worker = worker
        self.export_task_id = task_id
        self.export_button.setEnabled(False)
        self.export_progress.setVisible(True)
        worker.progress.connect(lambda percent, message: self._export_progress(task_id, percent, message))
        worker.completed.connect(self._export_completed)
        worker.failed.connect(self._export_failed)
        worker.cancelled.connect(self._export_cancelled)
        worker.finished.connect(self._export_finished)
        worker.start()

    def _export_progress(self, task_id: int, percent: float, message: str) -> None:
        self.main.task_center.update_task(task_id, "导出中", percent, message)
        self.export_progress.setRange(0, 1000)
        self.export_progress.setValue(round(min(100.0, percent) * 10))
        self.export_progress.setFormat(f"{message}  {min(100.0, percent):.1f}%")

    def _export_completed(self, project: Project, package: Path) -> None:
        self.main.current_project = self.main.database.save_project(project)
        self.main.refresh_library()
        if self.export_task_id is not None:
            self.main.task_center.update_task(self.export_task_id, "已完成", 100.0, str(package))
        QMessageBox.information(self, "导出完成", f"素材包已生成：\n{package}")
        if self.open_export_folder.isChecked():
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(package.resolve()))):
                self.main.show_status(f"无法自动打开导出目录：{package}", 8000)

    def _export_failed(self, message: str) -> None:
        if self.export_task_id is not None:
            self.main.task_center.update_task(self.export_task_id, "失败", 0.0, message)
        QMessageBox.warning(self, "导出失败", message)

    def _export_cancelled(self) -> None:
        if self.export_task_id is not None:
            self.main.task_center.update_task(self.export_task_id, "已取消", 0.0, "导出任务已取消")
        self.main.show_status("导出任务已取消", 8000)

    def _export_finished(self) -> None:
        if self.export_worker is not None:
            self.export_worker.deleteLater()
        self.export_worker = None
        self.export_task_id = None
        self.export_button.setEnabled(True)
        self.export_progress.setVisible(False)

    def cancel_task(self, task_id: int) -> bool:
        if self.export_worker is not None and self.export_task_id == task_id:
            self.export_worker.cancel()
            self.main.task_center.update_task(task_id, "正在取消", -1.0, "等待当前导出步骤安全停止…")
            return True
        return False


class LibraryTab(QWidget):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(); self.main = parent; layout = QVBoxLayout(self)
        self.list = CopyableListWidget(); self.list.itemDoubleClicked.connect(self.open_project); layout.addWidget(self.list)
        refresh = QPushButton("刷新资料库"); refresh.clicked.connect(self.main.refresh_library); layout.addWidget(refresh)

    def open_project(self, item: QListWidgetItem) -> None:
        project = self.main.database.get_project(item.data(Qt.ItemDataRole.UserRole)); self.main.current_project = project
        if project.status in {ProjectStatus.FAILED, ProjectStatus.CANCELLED} or not project.captions:
            self.main.import_tab.load_project(project)
            self.main.tabs.setCurrentWidget(self.main.import_tab)
        else:
            self.main.refresh_editor(); self.main.tabs.setCurrentWidget(self.main.editor)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__(); self.setWindowTitle("每日英语听力资源助手"); self.resize(1100, 720)
        self.database = LibraryDatabase(); self.pipeline = CaptionPipeline(); self.current_project: Project | None = None
        self._closing_tasks = False
        recovered_tasks = self.database.recover_interrupted_projects()
        self.tabs = QTabWidget(); self.task_center = TaskCenterTab(); self.search = SearchTab(self); self.import_tab = ImportTab(self); self.editor = EditorTab(self); self.library = LibraryTab(self); self.model_manager = ModelManagerTab(self)
        self.task_center.cancel_requested.connect(self.cancel_task)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.addTab(self.search, "资源搜索"); self.tabs.addTab(self.import_tab, "导入任务"); self.tabs.addTab(self.editor, "字幕预览"); self.tabs.addTab(self.model_manager, "模型管理"); self.tabs.addTab(self.library, "资料库"); self.setCentralWidget(self.tabs)
        self.tabs.addTab(self.task_center, "任务中心")
        self.status_message = QLabel()
        self.status_message.setWordWrap(True)
        self.statusBar().addWidget(self.status_message, 1)
        self.refresh_library()
        if recovered_tasks:
            self.show_status(f"已恢复 {recovered_tasks} 个上次中断的任务，可从资料库重新处理。", 15000)

    def cancel_task(self, task_id: int) -> None:
        if self.import_tab.cancel_task(task_id):
            return
        if self.editor.cancel_task(task_id):
            return
        if self.model_manager.cancel_task(task_id):
            return
        self.search.cancel_task(task_id)

    def show_status(self, message: str, timeout: int = 0) -> None:
        self.status_message.setText(message)
        if timeout:
            QTimer.singleShot(
                timeout,
                lambda current=message: self.status_message.clear()
                if self.status_message.text() == current else None,
            )

    def refresh_library(self) -> None:
        self.library.list.clear()
        for project in self.database.list_projects():
            item = QListWidgetItem(f"[{project.status.value}] {project.title} — {project.provider}")
            item.setData(Qt.ItemDataRole.UserRole, project.id); self.library.list.addItem(item)

    def refresh_editor(self) -> None:
        if self.current_project: self.editor.load(self.current_project)

    def _worker_threads(self) -> list[QThread]:
        workers: list[QThread] = list(self.search.workers)
        workers.extend(self.import_tab.active_workers)
        workers.extend(worker for worker, _task_id in self.import_tab.pending_workers)
        if self.editor.export_worker is not None:
            workers.append(self.editor.export_worker)
        if self.model_manager.worker is not None:
            workers.append(self.model_manager.worker)
        return workers

    def _cancel_all_tasks(self) -> None:
        for worker in list(self.search.workers):
            worker.cancel()
        for worker, task_id in list(self.import_tab.pending_workers):
            self.import_tab.cancel_task(task_id)
        for worker in list(self.import_tab.active_workers):
            worker.cancel()
        if self.editor.export_worker is not None:
            self.editor.export_worker.cancel()
        if self.model_manager.worker is not None:
            self.model_manager.worker.cancel()

    def closeEvent(self, event: QCloseEvent) -> None:
        workers = self._worker_threads()
        unfinished = [worker for worker in workers if worker.isRunning()]
        has_pending = bool(self.import_tab.pending_workers)
        if not unfinished and not has_pending:
            event.accept()
            return
        if not self._closing_tasks:
            answer = QMessageBox.question(
                self, "任务仍在进行",
                "仍有下载、转写或导出任务。是否取消这些任务并退出？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._closing_tasks = True
            self._cancel_all_tasks()
        unfinished = [worker for worker in self._worker_threads() if worker.isRunning()]
        if unfinished:
            self.show_status("正在等待后台任务安全停止…")
            event.ignore()
            QTimer.singleShot(750, self.close)
            return
        event.accept()


def run() -> None:
    application = QApplication(sys.argv)
    selectable_filter = SelectableLabelFilter(application)
    application.installEventFilter(selectable_filter)
    application._selectable_label_filter = selectable_filter
    window = MainWindow(); window.show(); sys.exit(application.exec())
