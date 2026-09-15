import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea

from daily_english.ui import (
    CopyableListWidget, EditorTab, ImportTab, SelectableLabelFilter, TaskCenterTab,
)


_APP = QApplication.instance() or QApplication([])


def test_labels_and_item_views_are_copyable() -> None:
    selectable_filter = SelectableLabelFilter(_APP)
    _APP.installEventFilter(selectable_filter)
    label = QLabel("可选择的信息")
    label.show()
    _APP.processEvents()
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse

    items = CopyableListWidget()
    items.addItem("可复制项目")
    items.setCurrentRow(0)
    items.show()
    items.setFocus()
    QTest.keyClick(items, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert _APP.clipboard().text() == "可复制项目"

    table_tab = TaskCenterTab()
    task_id = table_tab.add_task("字幕", "可复制任务")
    table_tab.update_task(task_id, "处理中", 50.0, "可复制详情")
    table_tab.table.selectRow(0)
    table_tab.table.show()
    table_tab.table.setFocus()
    QTest.keyClick(table_tab.table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    copied = _APP.clipboard().text()
    assert "可复制任务" in copied
    assert "可复制详情" in copied

    table_tab.close()
    items.close()
    label.close()
    _APP.removeEventFilter(selectable_filter)


def test_import_form_resizes_and_scrolls() -> None:
    task_center = TaskCenterTab()
    tab = ImportTab(SimpleNamespace(task_center=task_center))
    scroll = tab.findChild(QScrollArea)
    assert scroll is not None
    assert scroll.widgetResizable()

    tab.resize(520, 360)
    tab.show()
    _APP.processEvents()
    small_width = scroll.viewport().width()

    tab.resize(1200, 800)
    _APP.processEvents()
    assert scroll.viewport().width() > small_width
    tab.close()
    task_center.close()


def test_editor_has_open_export_folder_switch(monkeypatch) -> None:
    monkeypatch.setattr("daily_english.ui.bool_setting", lambda key, default: True)
    remembered: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "daily_english.ui.set_setting",
        lambda key, value: remembered.append((key, value)),
    )
    tab = EditorTab(SimpleNamespace(current_project=None))
    assert tab.open_export_folder.text() == "导出完成后打开文件夹"
    assert tab.open_export_folder.isChecked()

    tab.open_export_folder.setChecked(False)
    assert remembered[-1] == ("open_export_folder_after_export", False)
    tab.close()


def test_task_center_emits_cancel_for_selected_task() -> None:
    tab = TaskCenterTab()
    task_id = tab.add_task("字幕", "可取消任务")
    cancelled: list[int] = []
    tab.cancel_requested.connect(cancelled.append)
    tab.table.selectRow(tab.rows[task_id])
    tab.cancel_selected_tasks()
    assert cancelled == [task_id]
    tab.close()
