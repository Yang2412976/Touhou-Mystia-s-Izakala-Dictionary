import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

from queshi import load_dishes, search_by_tag

import sys
from PyQt5 import QtWidgets, QtGui, QtCore
import re

try:
    import pandas as pd
except Exception:
    pd = None


class QueshiGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("东方夜雀食堂食谱 ~ Made by Mikotototo")
        self.root.geometry("800x500")

        self.checkpoint = None

        # use a Canvas so we can draw a background image behind widgets
        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

# we'll place widgets directly on the canvas (so overlay panel can sit between bg and widgets)
"""
PyQt5 GUI for the queshi index program.
Features:
- Background image (scaled)
- Semi-transparent overlay panel with adjustable opacity so background shows through controls
- Search by tag and show results in a QTableView using a Pandas-backed model

Requires: PyQt5 (pip install PyQt5)
"""


class PandasModel(QtCore.QAbstractTableModel):
    def __init__(self, df=None, parent=None):
        super().__init__(parent)
        # avoid evaluating pd.DataFrame() at function definition time
        if df is None:
            if pd is not None:
                df = pd.DataFrame()
            else:
                df = []
        self._df = df

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if self._df.empty else len(self._df.columns)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == QtCore.Qt.DisplayRole:
            val = self._df.iat[index.row(), index.column()]
            return str(val)
        # make cell text bold by returning a QFont for the FontRole
        if role == QtCore.Qt.FontRole:
            f = QtGui.QFont()
            f.setBold(True)
            return f
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            return str(self._df.columns[section])
        else:
            return str(self._df.index[section])

    def setDataFrame(self, df):
        self.beginResetModel()
        self._df = df
        self.endResetModel()


class BackgroundWidget(QtWidgets.QWidget):
    """A QWidget that draws a QPixmap as its background, scaled to fill."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None

    def setPixmap(self, pixmap: QtGui.QPixmap | None):
        self._pixmap = pixmap
        self.update()
        # debug prints removed for release

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(self.size(), QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
            # center the pixmap
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            # fallback: fill with transparent background so stylesheet/parent shows
            painter.fillRect(self.rect(), self.palette().window())


class QueshiWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("东方夜雀食堂食谱 ~ Made by Mikotototo")
        self.resize(1000, 700)

        self.checkpoint = None
        self._bg_pixmap = None
        # determine background path robustly for both development and bundled exe
        candidates = []
        if getattr(sys, 'frozen', False):
            # when bundled by PyInstaller, check extracted _MEIPASS first, then exe dir
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass:
                candidates.append(meipass)
            candidates.append(os.path.dirname(sys.executable))
        else:
            # during development, prefer script dir
            candidates.append(os.path.dirname(__file__))
        # also check current working directory as a last resort (useful if user moved exe)
        candidates.append(os.getcwd())

        found = None
        for d in candidates:
            try:
                p = os.path.join(d, 'background.png')
            except Exception:
                continue
            if d and os.path.exists(p):
                found = p
                break

        # final fallback: same-dir as this script
        if not found:
            found = os.path.join(os.path.dirname(__file__), 'background.png')

        self._bg_path = found

        # central widget (custom draws background)
        self.central = BackgroundWidget()
        self.setCentralWidget(self.central)
        self.layout = QtWidgets.QVBoxLayout(self.central)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # overlay frame (semi-transparent) contains controls
        self.overlay = QtWidgets.QFrame(self.central)
        self.overlay.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.overlay_layout = QtWidgets.QHBoxLayout(self.overlay)
        self.overlay_layout.setContentsMargins(8, 8, 8, 8)
        self.overlay_layout.setSpacing(6)

        # controls
        self.label = QtWidgets.QLabel("标签:")
        self.entry = QtWidgets.QLineEdit()
        # enable event filter so we can show completion popup on focus
        self.entry.installEventFilter(self)
        self.search_btn = QtWidgets.QPushButton("搜索")
        self.search_btn.clicked.connect(self.on_search)

        self.alpha_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.alpha_slider.setRange(0, 100)
        # set initial transparency to minimum opacity (most transparent)
        self.alpha_slider.setValue(0)
        self.alpha_slider.valueChanged.connect(self.on_alpha_change)

        self.status_label = QtWidgets.QLabel("未加载数据")

        # assemble overlay
        self.overlay_layout.addWidget(self.label)
        self.overlay_layout.addWidget(self.entry)
        self.overlay_layout.addWidget(self.search_btn)
        self.overlay_layout.addWidget(QtWidgets.QLabel("透明度"))
        self.overlay_layout.addWidget(self.alpha_slider)
        self.overlay_layout.addWidget(self.status_label)

        # table view
        self.table = QtWidgets.QTableView(self.central)
        self.model = PandasModel(pd.DataFrame()) if pd is not None else None
        if self.model:
            self.table.setModel(self.model)

        # make header font bold
        try:
            hf = self.table.horizontalHeader().font()
            hf.setBold(True)
            self.table.horizontalHeader().setFont(hf)
        except Exception:
            pass

        # make result area semi-transparent so background shows through
        self.table.setStyleSheet("QTableView { background: rgba(255,255,255,180); }")
        try:
            self.table.horizontalHeader().setStyleSheet("QHeaderView::section { background: rgba(255,255,255,200); }")
        except Exception:
            pass

    # add overlay and table to layout
        self.layout.addWidget(self.overlay)
        self.layout.addWidget(self.table)

        # apply initial opacity
        self._apply_opacity(self.alpha_slider.value() / 100.0)

        # load default background if present
        if os.path.exists(self._bg_path):
            self.set_background(self._bg_path)

        # load data
        self.load_data()

        # ensure completer initialized after loading data
        try:
            self._update_tag_completer()
        except Exception:
            pass

        # menu bar: 功能 -> 加载数据/选择背景
        menubar = self.menuBar()
        func_menu = menubar.addMenu("功能")

        load_action = QtWidgets.QAction("加载数据", self)
        load_action.triggered.connect(self.on_load)
        func_menu.addAction(load_action)

        bg_action = QtWidgets.QAction("选择背景", self)
        bg_action.triggered.connect(self.on_select_background)
        func_menu.addAction(bg_action)

        # add search and opacity actions to 功能 menu
        search_action = QtWidgets.QAction("按标签搜索", self)
        search_action.triggered.connect(self.menu_search)
        func_menu.addAction(search_action)

        opacity_action = QtWidgets.QAction("调整透明度...", self)
        opacity_action.triggered.connect(self.menu_adjust_opacity)
        func_menu.addAction(opacity_action)

    def menu_search(self):
        # ask for a tag and perform search
        tag, ok = QtWidgets.QInputDialog.getText(self, "按标签搜索", "标签:")
        if not ok:
            return
        tag = tag.strip()
        if not tag:
            QtWidgets.QMessageBox.information(self, "提示", "请输入标签再搜索")
            return
        try:
            results = search_by_tag(tag, self.checkpoint)
            if self.model:
                self.model.setDataFrame(results.copy())
            else:
                m = PandasModel(results.copy())
                self.table.setModel(m)
            self.status_label.setText(f"完成: {len(results)} 条结果")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"搜索失败: {e}")

    def _update_tag_completer(self):
        """Build/update a QCompleter for tag suggestions based on loaded data."""
        if self.checkpoint is None or (hasattr(self.checkpoint, 'empty') and self.checkpoint.empty):
            tags = []
        else:
            # expect checkpoint to have a 'tags' column where each entry is iterable
            tags_set = set()
            try:
                for item in self.checkpoint['tags']:
                    if item is None:
                        continue
                    # if tags is a string like 'a,b', try to split by non-word separators
                    if isinstance(item, str):
                        parts = re.split(r'\W+', item)
                        for p in parts:
                            p = p.strip()
                            if p:
                                tags_set.add(p)
                    else:
                        try:
                            for t in item:
                                tags_set.add(str(t))
                        except Exception:
                            tags_set.add(str(item))
            except Exception:
                tags_set = set()
            tags = sorted(tags_set)

        # remember tag list for popup fallback
        self._tag_list = tags

        # ensure popup fallback exists
        try:
            if not hasattr(self, '_tag_popup') or self._tag_popup is None:
                popup = QtWidgets.QListWidget(self)
                popup.setWindowFlags(QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
                popup.setFocusPolicy(QtCore.Qt.NoFocus)
                popup.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                popup.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
                popup.itemClicked.connect(self._on_popup_item_clicked)
                self._tag_popup = popup
        except Exception:
            self._tag_popup = None

        # create completer and keep a reference to the model so we can inspect rows
        try:
            model = QtCore.QStringListModel(tags)
            completer = QtWidgets.QCompleter(self.entry)
            completer.setModel(model)
            completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
            completer.setFilterMode(QtCore.Qt.MatchContains)
            completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
            completer.setMaxVisibleItems(10)
            self.entry.setCompleter(completer)
            self._tag_completer = completer
            self._tag_model = model
        except Exception:
            # PyQt versions may differ; fallback to simple QCompleter from list
            try:
                # fallback: build a QStringListModel and set it explicitly
                model = QtCore.QStringListModel(tags)
                completer = QtWidgets.QCompleter(self.entry)
                completer.setModel(model)
                completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
                completer.setFilterMode(QtCore.Qt.MatchContains)
                completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
                completer.setMaxVisibleItems(10)
                self.entry.setCompleter(completer)
                self._tag_completer = completer
                self._tag_model = model
            except Exception:
                self._tag_completer = None
        # connect textEdited to update completion popup dynamically
        try:
            if getattr(self, '_tag_completer', None) is not None:
                # ensure we don't connect multiple times
                try:
                    self.entry.textEdited.disconnect(self._on_entry_text_edited)
                except Exception:
                    pass
                self.entry.textEdited.connect(self._on_entry_text_edited)
        except Exception:
            pass

    def _show_tag_popup(self, prefix: str):
        try:
            popup = getattr(self, '_tag_popup', None)
            if popup is None:
                return
            popup.clear()
            prefix = (prefix or '').strip()
            # filter tags case-insensitive contains
            for t in getattr(self, '_tag_list', []):
                if not prefix or prefix.lower() in t.lower():
                    popup.addItem(t)
            if popup.count() == 0:
                popup.hide()
                return
            # position below entry
            gpos = self.entry.mapToGlobal(QtCore.QPoint(0, self.entry.height()))
            popup.setFixedWidth(max(self.entry.width(), 150))
            popup.move(gpos)
            popup.show()
        except Exception:
            pass

    def _hide_tag_popup(self):
        try:
            popup = getattr(self, '_tag_popup', None)
            if popup is not None:
                popup.hide()
        except Exception:
            pass

    def _on_popup_item_clicked(self, item):
        try:
            text = item.text()
            self.entry.setText(text)
            self._hide_tag_popup()
            # optionally trigger search immediately
            try:
                self.on_search()
            except Exception:
                pass
        except Exception:
            pass

    def eventFilter(self, obj, event):
        # Show completer popup when the entry gains focus
        try:
            if obj is self.entry:
                # show popup on focus in (delay slightly so layout finishes)
                if event.type() == QtCore.QEvent.FocusIn:
                    comp = getattr(self, '_tag_completer', None)
                    if comp is not None:
                        try:
                            model = comp.model() or getattr(self, '_tag_model', None)
                            count = model.rowCount(QtCore.QModelIndex()) if model is not None else 0
                        except Exception:
                            try:
                                count = model.rowCount()
                            except Exception:
                                count = 0
                        if count > 0:
                            prefix = self.entry.text() or ''
                            comp.setCompletionPrefix(prefix)
                            # delay completion slightly to ensure popup positions correctly
                            try:
                                QtCore.QTimer.singleShot(60, lambda: comp.complete(self.entry.rect()))
                            except Exception:
                                try:
                                    QtCore.QTimer.singleShot(60, comp.complete)
                                except Exception:
                                    comp.complete()
                # open popup when user presses Down key
                if event.type() == QtCore.QEvent.KeyPress:
                    try:
                        if event.key() == QtCore.Qt.Key_Down:
                            comp = getattr(self, '_tag_completer', None)
                            if comp is not None:
                                try:
                                    comp.complete(self.entry.rect())
                                except Exception:
                                    comp.complete()
                    except Exception:
                        pass
                # hide popup on focus out
                if event.type() == QtCore.QEvent.FocusOut:
                    try:
                        self._hide_tag_popup()
                    except Exception:
                        pass
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _on_entry_text_edited(self, text: str):
        try:
            comp = getattr(self, '_tag_completer', None)
            if comp is None:
                return
            # update prefix and show popup (even if text empty we show suggestions)
            comp.setCompletionPrefix(text or '')
            # only show if there are items
            try:
                model = comp.model()
                count = model.rowCount(QtCore.QModelIndex()) if model is not None else 0
            except Exception:
                try:
                    count = model.rowCount()
                except Exception:
                    count = 0
            if count > 0:
                try:
                    comp.complete(self.entry.rect())
                    # also ensure fallback popup hidden
                    self._hide_tag_popup()
                    return
                except Exception:
                    try:
                        comp.complete()
                        self._hide_tag_popup()
                        return
                    except Exception:
                        pass
            # fallback: show our popup list
            try:
                self._show_tag_popup(text)
            except Exception:
                pass
        except Exception:
            pass

    def menu_adjust_opacity(self):
        # ask for opacity percentage
        val, ok = QtWidgets.QInputDialog.getInt(self, "调整透明度", "透明度 (0-100，100 代表更透明):", int(self.alpha_slider.value()), 0, 100)
        if not ok:
            return
        self.alpha_slider.setValue(val)

    def on_alpha_change(self, v):
        a = self.alpha_slider.value() / 100.0
        self._apply_opacity(a)

    def _apply_opacity(self, alpha: float):
        """Apply overlay and table background opacity.

        alpha: fraction 0.0-1.0 where 1.0 means fully transparent overlay (background shows through)
        """
        # overlay: compute panel alpha (0-255), lower value = more transparent
        opa = int((1 - alpha) * 255)
        self.overlay.setStyleSheet(self._overlay_style(alpha))
        # table: use a slightly stronger transparency so results area shows more background
        table_opa = int(opa * 0.6)
        # enforce within 0-255
        table_opa = max(0, min(255, table_opa))
        self.table.setStyleSheet(f"QTableView {{ background-color: rgba(255,255,255,{table_opa}); }}")

    def _overlay_style(self, alpha: float) -> str:
        """Return a stylesheet string for the overlay frame based on alpha (0.0-1.0).

        alpha is fraction where 0.0 = fully opaque panel, 1.0 = fully transparent.
        """
        opa = int((1 - alpha) * 255)
        opa = max(0, min(255, opa))
        return f"background-color: rgba(255,255,255,{opa}); border-radius:8px;"

    def set_background(self, path):
        try:
            pix = QtGui.QPixmap(path)
            self._bg_pixmap = pix
            # hand pixmap to background widget which will paint it
            if isinstance(self.central, BackgroundWidget):
                self.central.setPixmap(self._bg_pixmap)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "错误", f"设置背景失败: {e}")

    def on_select_background(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择背景图片", os.path.expanduser("~"), "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)")
        if path:
            self.set_background(path)

    def load_data(self):
        try:
            self.checkpoint = load_dishes()
            self.status_label.setText(f"数据已加载 ({len(self.checkpoint)})")
            try:
                self._update_tag_completer()
            except Exception:
                pass
        except Exception as e:
            self.status_label.setText("加载失败")

    def on_load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 dishes.txt", os.path.expanduser("~"), "Text Files (*.txt);;All Files (*)")
        if not path:
            return
        try:
            ns = {}
            with open(path, 'r', encoding='utf-8') as f:
                exec(f.read(), ns)
            dishes = ns['dishes']
            self.checkpoint = pd.DataFrame(dishes)
            self.status_label.setText(f"数据已加载 ({len(self.checkpoint)})")
            try:
                self._update_tag_completer()
            except Exception:
                pass
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"加载文件失败: {e}")

    def on_search(self):
        tag = self.entry.text().strip()
        if not tag:
            QtWidgets.QMessageBox.information(self, "提示", "请输入标签再搜索")
            return
        try:
            results = search_by_tag(tag, self.checkpoint)
            # show only name/tags/price columns if exist
            if 'price' in results.columns:
                show_df = results.copy()
            else:
                show_df = results.copy()
            if self.model:
                self.model.setDataFrame(show_df)
            else:
                # fallback: set model directly
                m = PandasModel(show_df)
                self.table.setModel(m)
            self.status_label.setText(f"完成: {len(results)} 条结果")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"搜索失败: {e}")


def main():
    if not QtWidgets.QApplication.instance():
        app = QtWidgets.QApplication(sys.argv)
    else:
        app = QtWidgets.QApplication.instance()
    win = QueshiWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('运行 GUI 失败:', e)
        # update treeview in main thread
