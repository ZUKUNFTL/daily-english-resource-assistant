from __future__ import annotations

import sys
import webbrowser
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QComboBox, QCheckBox, QProgressBar,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .database import LibraryDatabase
from .engine import EngineRunner
from .models import DownloadStatus, Project, ProjectStatus, Resource
from .pipeline import CaptionPipeline
from .providers import BilibiliProvider, TedProvider, YouTubeProvider, bilibili_search_url
from .downloader import DownloadResult, WeChatChannelsDownloader, YtDlpDownloader, detect_platform
from .settings import load_settings, save_settings


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
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self.open_resource)
        layout.addWidget(self.results)
        actions = QHBoxLayout()
        self.audio_button = QPushButton("下载音频 MP3")
        self.video_button = QPushButton("下载视频 MP4")
        self.audio_button.clicked.connect(lambda: self.download_selected("audio"))
        self.video_button.clicked.connect(lambda: self.download_selected("video"))
        actions.addWidget(self.audio_button); actions.addWidget(self.video_button)
        self.progress = QLabel("")
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

    def download_selected(self, media_kind: str) -> None:
        item = self.results.currentItem()
        if item is None:
            QMessageBox.information(self, "未选择资源", "请先选择一个搜索结果或直接粘贴链接搜索。")
            return
        resource: Resource = item.data(Qt.ItemDataRole.UserRole)
        destination = QFileDialog.getExistingDirectory(self, "选择下载目录")
        if not destination:
            return
        worker = DownloadWorker(resource.download_url or resource.url, destination, media_kind)
        task_id = self.main.task_center.add_task("下载", resource.title)
        self.workers[worker] = task_id
        worker.progress.connect(lambda percent, text, current=task_id: self._download_progress(current, percent, text))
        worker.completed.connect(lambda result, current=worker: self.download_completed(current, result))
        worker.failed.connect(lambda message, current=worker: self.download_failed(current, message))
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
        self.main.statusBar().showMessage(f"下载完成并已加入资料库：{result.path}", 12000)

    def download_failed(self, worker: "DownloadWorker", message: str) -> None:
        task_id = self.workers[worker]
        self.main.task_center.update_task(task_id, "失败", 0.0, message)
        self.progress.setText("下载失败")
        QMessageBox.warning(self, "下载失败", message)

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

    def __init__(self, url: str, destination: str, media_kind: str) -> None:
        super().__init__(); self.url = url; self.destination = destination; self.media_kind = media_kind

    def run(self) -> None:
        try:
            result = YtDlpDownloader().download(self.url, self.destination, self.media_kind, self.progress.emit)
            self.completed.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


class ProcessWorker(QThread):
    progress = Signal(float, str)
    completed = Signal(object)
    failed = Signal(object, str)

    def __init__(self, project: Project, model_name: str) -> None:
        super().__init__()
        self.project = project
        self.model_name = model_name

    def run(self) -> None:
        try:
            pipeline = CaptionPipeline()
            if not self.project.captions:
                pipeline.transcribe(self.project, self.model_name, self.progress.emit)
            else:
                self.progress.emit(85.0, "已有原文字幕，跳过语音转写")
            pipeline.translate_missing(self.project, self.progress.emit)
            self.progress.emit(100.0, "处理完成")
            self.completed.emit(self.project)
        except Exception as error:
            self.failed.emit(self.project, str(error))


class TaskCenterTab(QWidget):
    concurrency_changed = Signal(int)

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
        options.addStretch(1)
        layout.addLayout(options)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["类型", "项目", "状态", "进度", "详情"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        hint = QLabel("下载可同时进行；转写默认串行。内存充足时可切换为 2 个并发任务。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def max_processing_workers(self) -> int:
        return int(self.processing_concurrency.currentData())

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
        self.table.resizeColumnsToContents()
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


class ImportTab(QWidget):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(); self.main = parent
        self.pending_workers: deque[tuple[ProcessWorker, int]] = deque()
        self.active_workers: dict[ProcessWorker, int] = {}
        self.queued_project_ids: set[int] = set()
        layout = QFormLayout(self)
        self.title = QLineEdit(); self.author = QLineEdit(); self.url = QLineEdit()
        self.media = QLineEdit(); self.reference = QLineEdit(); self.subtitle = QLineEdit()
        self.source_language = QComboBox(); self.source_language.addItem("自动检测", "auto"); self.source_language.addItem("中文", "zh-cn"); self.source_language.addItem("英语", "en")
        self.target_language = QComboBox(); self.target_language.addItem("英语", "en"); self.target_language.addItem("中文", "zh")
        self.source_language.currentIndexChanged.connect(self._update_target_language)
        self.model_name = QComboBox(); self.model_name.addItems(["small", "medium", "large-v3"])
        self.alignment = QCheckBox("启用 WhisperX/词级对齐（sidecar 可用时）")
        self.engine_status = QLabel()
        self.refresh_engine_status()
        layout.addRow("标题", self.title); layout.addRow("作者", self.author); layout.addRow("来源链接", self.url)
        layout.addRow("源语言", self.source_language); layout.addRow("目标语言", self.target_language)
        layout.addRow("识别模型", self.model_name); layout.addRow("对齐", self.alignment); layout.addRow("处理引擎", self.engine_status)
        layout.addRow("本地媒体", self._picker(self.media, "媒体文件", "音频或视频 (*.*)"))
        layout.addRow("参考文稿", self._picker(self.reference, "参考文稿", "文稿 (*.txt *.docx *.pdf)"))
        layout.addRow("已有字幕", self._picker(self.subtitle, "SRT 字幕", "字幕 (*.srt)"))
        self.process_progress = QProgressBar(); self.process_progress.setRange(0, 1000); self.process_progress.setValue(0)
        self.process_message = QLabel("尚未开始")
        layout.addRow("当前进度", self.process_progress); layout.addRow("处理状态", self.process_message)
        buttons = QHBoxLayout(); import_button = QPushButton("建立项目")
        import_button.clicked.connect(self.create_project); process_button = QPushButton("加入处理队列")
        process_button.clicked.connect(self.process_project); buttons.addWidget(import_button); buttons.addWidget(process_button)
        layout.addRow(buttons)
        self.main.task_center.concurrency_changed.connect(lambda _count: self._start_pending())

    def refresh_engine_status(self) -> None:
        status = EngineRunner().status()
        self.engine_status.setText(("可用：" if status.available else "未安装：") + status.message)

    def _update_target_language(self) -> None:
        source = self.source_language.currentData()
        target = "en" if source == "zh-cn" else "zh"
        index = self.target_language.findData(target)
        if index >= 0:
            self.target_language.setCurrentIndex(index)

    def _picker(self, field: QLineEdit, title: str, filter_text: str) -> QWidget:
        widget = QWidget(); row = QHBoxLayout(widget); row.setContentsMargins(0, 0, 0, 0); row.addWidget(field)
        button = QPushButton("选择"); button.clicked.connect(lambda: self.pick(field, title, filter_text)); row.addWidget(button); return widget

    def pick(self, field: QLineEdit, title: str, filter_text: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, "", filter_text)
        if path: field.setText(path)

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
        worker.finished.connect(lambda current=worker: self._process_finished(current))
        self.pending_workers.append((worker, task_id))
        self.queued_project_ids.add(project.id)
        self.main.refresh_library()
        self.process_message.setText("任务已加入队列")
        self._start_pending()

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
        self.main.statusBar().showMessage(f"字幕任务完成：{project.title}", 12000)

    def _process_failed(self, worker: ProcessWorker, project: Project, message: str) -> None:
        project.status = ProjectStatus.FAILED
        project.error = message
        self.main.database.save_project(project)
        task_id = self.active_workers[worker]
        self.main.task_center.update_task(task_id, "失败", 0.0, message)
        self.process_progress.setRange(0, 1000); self.process_progress.setValue(0)
        self.process_message.setText(f"处理失败：{message}")
        self.main.refresh_library()

    def _process_finished(self, worker: ProcessWorker) -> None:
        self.active_workers.pop(worker, None)
        if worker.project.id is not None:
            self.queued_project_ids.discard(worker.project.id)
        worker.deleteLater()
        self._start_pending()


class EditorTab(QWidget):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(); self.main = parent
        layout = QVBoxLayout(self); self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["开始(s)", "结束(s)", "原文", "译文"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); layout.addWidget(self.table)
        buttons = QHBoxLayout(); save = QPushButton("保存修改"); save.clicked.connect(self.save)
        export = QPushButton("导出 MP3 + SRT"); export.clicked.connect(self.export)
        buttons.addWidget(save); buttons.addWidget(export); layout.addLayout(buttons)

    def load(self, project: Project) -> None:
        self.table.setRowCount(len(project.captions))
        for row, caption in enumerate(project.captions):
            for column, value in enumerate((f"{caption.start:.3f}", f"{caption.end:.3f}", caption.source_text, caption.translated_text)):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

    def save(self) -> None:
        project = self.main.current_project
        if project is None: return
        try:
            for row, caption in enumerate(project.captions):
                caption.start = float(self.table.item(row, 0).text()); caption.end = float(self.table.item(row, 1).text())
                caption.source_text = self.table.item(row, 2).text(); caption.translated_text = self.table.item(row, 3).text()
            self.main.current_project = self.main.database.save_project(project); QMessageBox.information(self, "已保存", "字幕修改已保存。")
        except Exception as error: QMessageBox.warning(self, "保存失败", str(error))

    def export(self) -> None:
        self.save(); project = self.main.current_project
        if project is None: return
        destination = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not destination: return
        try:
            package = CaptionPipeline().export_package(project, destination, create_zip=True)
            self.main.current_project = self.main.database.save_project(project); self.main.refresh_library()
            QMessageBox.information(self, "导出完成", f"素材包已生成：\n{package}")
        except Exception as error: QMessageBox.warning(self, "导出失败", str(error))


class LibraryTab(QWidget):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(); self.main = parent; layout = QVBoxLayout(self)
        self.list = QListWidget(); self.list.itemDoubleClicked.connect(self.open_project); layout.addWidget(self.list)
        refresh = QPushButton("刷新资料库"); refresh.clicked.connect(self.main.refresh_library); layout.addWidget(refresh)

    def open_project(self, item: QListWidgetItem) -> None:
        project = self.main.database.get_project(item.data(Qt.ItemDataRole.UserRole)); self.main.current_project = project
        self.main.refresh_editor(); self.main.tabs.setCurrentWidget(self.main.editor)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__(); self.setWindowTitle("每日英语听力资源助手"); self.resize(1100, 720)
        self.database = LibraryDatabase(); self.pipeline = CaptionPipeline(); self.current_project: Project | None = None
        self.tabs = QTabWidget(); self.task_center = TaskCenterTab(); self.search = SearchTab(self); self.import_tab = ImportTab(self); self.editor = EditorTab(self); self.library = LibraryTab(self)
        self.tabs.addTab(self.search, "资源搜索"); self.tabs.addTab(self.import_tab, "导入任务"); self.tabs.addTab(self.editor, "字幕预览"); self.tabs.addTab(self.library, "资料库"); self.setCentralWidget(self.tabs)
        self.tabs.addTab(self.task_center, "任务中心")
        self.refresh_library()

    def refresh_library(self) -> None:
        self.library.list.clear()
        for project in self.database.list_projects():
            item = QListWidgetItem(f"[{project.status.value}] {project.title} — {project.provider}")
            item.setData(Qt.ItemDataRole.UserRole, project.id); self.library.list.addItem(item)

    def refresh_editor(self) -> None:
        if self.current_project: self.editor.load(self.current_project)


def run() -> None:
    application = QApplication(sys.argv); window = MainWindow(); window.show(); sys.exit(application.exec())
