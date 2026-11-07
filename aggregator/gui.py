"""Главное окно StroyAgg (PySide6)."""
from __future__ import annotations

import logging
import traceback
import webbrowser
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QSplitter, QTableView, QVBoxLayout, QWidget, QAbstractItemView,
)

from . import __version__
from .config import AppConfig, DbConfig
from .db import Database
from .importer import load_queries
from .models import Offer, mark_best
from .scraper import CaptchaError, Scraper, Site, load_sites

log = logging.getLogger(__name__)

COLUMNS = ["Запрос", "Площадка", "Наименование", "Цена, ₽", "Доставка", "Дней", "Дата", "Ссылка на заказ"]
GREEN = QColor("#d8f3dc")
BLUE = QColor("#dbeafe")
BOTH = QColor("#bde0c6")


# ---------------------------------------------------------------- модель таблицы
class OffersModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.offers: list[Offer] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.offers)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        o = self.offers[index.row()]
        c = index.column()
        if role == Qt.DisplayRole:
            return [
                o.query, o.marketplace, o.title,
                f"{o.price:,.2f}".replace(",", " ") if o.price is not None else "—",
                o.delivery_text or "—",
                "" if o.delivery_days is None else str(o.delivery_days),
                o.delivery_date.strftime("%d.%m.%Y") if o.delivery_date else "",
                o.url,
            ][c]
        if role == Qt.UserRole:  # значение для сортировки
            return [o.query.lower(), o.marketplace, o.title.lower(),
                    o.price if o.price is not None else 1e15, o.delivery_text,
                    o.delivery_days if o.delivery_days is not None else 10_000,
                    o.delivery_date.toordinal() if o.delivery_date else 10**7, o.url][c]
        if role == Qt.BackgroundRole:
            if o.is_best_price and o.is_fastest:
                return QBrush(BOTH)
            if o.is_best_price and c in (0, 3):
                return QBrush(GREEN)
            if o.is_fastest and c in (4, 5, 6):
                return QBrush(BLUE)
        if role == Qt.FontRole and ((c == 3 and o.is_best_price) or (c in (5, 6) and o.is_fastest)):
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ForegroundRole and c == 7:
            return QBrush(QColor("#1d4ed8"))
        if role == Qt.ToolTipRole:
            tip = [o.title, o.url]
            if o.is_best_price:
                tip.append("★ Лучшая цена по запросу")
            if o.is_fastest:
                tip.append("⚡ Самая быстрая доставка по запросу")
            return "\n".join(tip)
        if role == Qt.TextAlignmentRole and c in (3, 5, 6):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def set_offers(self, offers: list[Offer]):
        self.beginResetModel()
        self.offers = offers
        mark_best(self.offers)
        self.endResetModel()

    def add(self, offers: list[Offer]):
        self.set_offers(self.offers + offers)


# ---------------------------------------------------------------- фоновые задачи
class SearchWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    found = Signal(list)

    def __init__(self, queries: list[str], sites: list[Site], limit: int, headless: bool, deep: bool, timeout_s: int):
        super().__init__()
        self.queries, self.sites, self.limit = queries, sites, limit
        self.headless, self.deep, self.timeout_s = headless, deep, timeout_s
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self.queries) * len(self.sites)
        done = 0
        try:
            with Scraper(headless=self.headless, timeout_s=self.timeout_s, log_cb=self.log.emit,
                         stop_cb=lambda: self._stop) as sc:
                for q in self.queries:
                    for site in self.sites:
                        if self._stop:
                            self.log.emit("Остановлено пользователем")
                            return
                        self.log.emit(f"🔎 {site.name}: «{q}»…")
                        try:
                            offers = sc.search(site, q, self.limit, self.deep)
                            self.log.emit(f"   найдено: {len(offers)}")
                            if offers:
                                self.found.emit(offers)
                        except CaptchaError as e:
                            self.log.emit(f"   ⚠ {e}")
                        except Exception as e:  # noqa: BLE001
                            self.log.emit(f"   ⚠ {site.name}: ошибка — {e}")
                            log.exception("search failed")
                        done += 1
                        self.progress.emit(done, total)
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"❌ {e}")
            log.exception("worker failed")


class SetupBrowserWorker(QThread):
    log = Signal(str)

    def __init__(self, urls: list[str]):
        super().__init__()
        self.urls = urls
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            with Scraper(headless=False, log_cb=self.log.emit) as sc:
                sc.open_for_setup(self.urls)
                self.log.emit("Браузер открыт: выберите город доставки, при необходимости войдите и пройдите проверки. "
                              "Затем закройте окно браузера.")
                while not self._stop and sc.ctx.pages:
                    sc.ctx.pages[0].wait_for_timeout(500)
        except Exception as e:  # noqa: BLE001
            if not self._stop:
                self.log.emit(f"Браузер: {e}")


class SaveWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: DbConfig, offers: list[Offer]):
        super().__init__()
        self.cfg, self.offers = cfg, offers

    def run(self):
        try:
            run_id = Database(self.cfg).save(self.offers)
            self.done.emit(f"Сохранено в БД: {len(self.offers)} предложений (поиск №{run_id})")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------------------------------------------------------- диалог БД
class DbDialog(QDialog):
    def __init__(self, cfg: DbConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подключение к PostgreSQL")
        self.host = QLineEdit(cfg.host)
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(cfg.port)
        self.dbname = QLineEdit(cfg.dbname)
        self.user = QLineEdit(cfg.user)
        self.password = QLineEdit(cfg.password); self.password.setEchoMode(QLineEdit.Password)
        self.ssl = QComboBox(); self.ssl.addItems(["prefer", "disable", "require", "verify-full"])
        self.ssl.setCurrentText(cfg.sslmode)
        form = QFormLayout()
        for label, w in (("Сервер", self.host), ("Порт", self.port), ("База данных", self.dbname),
                         ("Пользователь", self.user), ("Пароль", self.password), ("SSL", self.ssl)):
            form.addRow(label, w)
        test_btn = QPushButton("Проверить подключение")
        init_btn = QPushButton("Создать таблицы")
        test_btn.clicked.connect(self._test)
        init_btn.clicked.connect(self._init)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        row = QHBoxLayout(); row.addWidget(test_btn); row.addWidget(init_btn); lay.addLayout(row)
        lay.addWidget(bb)

    def value(self) -> DbConfig:
        return DbConfig(self.host.text().strip(), self.port.value(), self.dbname.text().strip(),
                        self.user.text().strip(), self.password.text(), self.ssl.currentText())

    def _test(self):
        try:
            v = Database(self.value()).test()
            QMessageBox.information(self, "Подключение", f"Успешно.\n{v[:80]}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Подключение", f"Ошибка подключения:\n{e}")

    def _init(self):
        try:
            Database(self.value()).init_schema()
            QMessageBox.information(self, "БД", "Таблицы offers, search_runs и представления созданы.")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "БД", str(e))


# ---------------------------------------------------------------- главное окно
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"StroyAgg — поиск строительных товаров на маркетплейсах  v{__version__}")
        self.resize(1400, 860)
        self.cfg = AppConfig.load()
        self.sites = load_sites()
        self.queue: list[str] = []
        self.worker: SearchWorker | None = None
        self.setup_worker: SetupBrowserWorker | None = None
        self.save_worker: SaveWorker | None = None

        # --- запрос
        self.query = QLineEdit()
        self.query.setPlaceholderText("Наименование или артикул, например: «саморез по дереву 3,5х35» или «Knauf Ротбанд 30 кг»")
        self.query.returnPressed.connect(self.search_one)
        self.btn_search = QPushButton("Найти")
        self.btn_search.setDefault(True)
        self.btn_search.clicked.connect(self.search_one)
        self.btn_import = QPushButton("Список из файла…")
        self.btn_import.setToolTip("CSV, XLSX или TXT: первый столбец — наименование/артикул")
        self.btn_import.clicked.connect(self.import_list)
        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        top = QHBoxLayout()
        top.addWidget(self.query, 1)
        for b in (self.btn_search, self.btn_import, self.btn_stop):
            top.addWidget(b)

        # --- площадки и опции
        box = QGroupBox("Площадки и параметры")
        opts = QHBoxLayout(box)
        self.site_checks: dict[str, QCheckBox] = {}
        enabled = set(self.cfg.search.enabled_sites) or {s.id for s in self.sites if s.enabled}
        for s in self.sites:
            cb = QCheckBox(s.name)
            cb.setChecked(s.id in enabled)
            self.site_checks[s.id] = cb
            opts.addWidget(cb)
        opts.addStretch(1)
        opts.addWidget(QLabel("Макс. на площадку:"))
        self.limit = QSpinBox(); self.limit.setRange(1, 100); self.limit.setValue(self.cfg.search.max_per_site)
        opts.addWidget(self.limit)
        self.headless = QCheckBox("Скрытый режим")
        self.headless.setToolTip("Браузер не показывается. Если площадка спросит «я не робот», снимите галочку.")
        self.headless.setChecked(self.cfg.search.headless)
        opts.addWidget(self.headless)
        self.deep = QCheckBox("Уточнять доставку в карточках")
        self.deep.setToolTip("Открывать страницы товаров, где срок доставки не указан в выдаче (медленнее)")
        self.deep.setChecked(self.cfg.search.deep_delivery)
        opts.addWidget(self.deep)

        # --- фильтр и действия
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Фильтр по таблице…")
        self.only_best = QCheckBox("Только лучшие (цена/доставка)")
        self.btn_save = QPushButton("💾 Сохранить в БД")
        self.btn_save.clicked.connect(self.save_db)
        self.btn_save_sel = QPushButton("Сохранить выделенные")
        self.btn_save_sel.clicked.connect(lambda: self.save_db(selected_only=True))
        self.btn_excel = QPushButton("Экспорт в Excel")
        self.btn_excel.clicked.connect(self.export_excel)
        self.btn_clear = QPushButton("Очистить")
        self.btn_clear.clicked.connect(lambda: self.model.set_offers([]))
        act = QHBoxLayout()
        act.addWidget(self.filter, 1)
        act.addWidget(self.only_best)
        for b in (self.btn_save, self.btn_save_sel, self.btn_excel, self.btn_clear):
            act.addWidget(b)

        # --- таблица
        self.model = OffersModel()
        self.proxy = BestFilterProxy(self.only_best)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.UserRole)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.only_best.toggled.connect(lambda _: self.proxy.invalidateFilter())
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(3, Qt.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.doubleClicked.connect(self.open_link)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        for col, w in ((0, 170), (1, 150), (3, 100), (4, 230), (5, 50), (6, 85), (7, 260)):
            self.table.setColumnWidth(col, w)
        self.table.verticalHeader().setDefaultSectionSize(26)

        legend = QLabel("<span style='background:#d8f3dc'>&nbsp;зелёный&nbsp;</span> — лучшая цена по запросу, "
                        "<span style='background:#dbeafe'>&nbsp;синий&nbsp;</span> — самая быстрая доставка. "
                        "Двойной щелчок по строке — открыть товар для заказа.")

        self.logbox = QPlainTextEdit(); self.logbox.setReadOnly(True); self.logbox.setMaximumBlockCount(3000)
        self.progress = QProgressBar(); self.progress.setVisible(False)

        split = QSplitter(Qt.Vertical)
        tw = QWidget(); tl = QVBoxLayout(tw); tl.setContentsMargins(0, 0, 0, 0)
        tl.addLayout(act); tl.addWidget(self.table); tl.addWidget(legend)
        split.addWidget(tw); split.addWidget(self.logbox)
        split.setSizes([640, 160])

        central = QWidget(); lay = QVBoxLayout(central)
        lay.addLayout(top); lay.addWidget(box); lay.addWidget(split, 1); lay.addWidget(self.progress)
        self.setCentralWidget(central)

        # --- меню
        m = self.menuBar().addMenu("Настройки")
        a_db = QAction("Подключение к PostgreSQL…", self); a_db.triggered.connect(self.db_settings); m.addAction(a_db)
        a_br = QAction("Открыть браузер: город доставки / вход / капча…", self); a_br.triggered.connect(self.setup_browser)
        m.addAction(a_br)
        self.statusBar().showMessage("Готово")
        self.log("Совет: перед первым поиском откройте «Настройки → Открыть браузер» и выберите город доставки на каждой площадке.")

    # ------------------------------------------------ helpers
    def log(self, text: str):
        self.logbox.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def selected_sites(self) -> list[Site]:
        return [s for s in self.sites if self.site_checks[s.id].isChecked()]

    def _persist_options(self):
        s = self.cfg.search
        s.max_per_site, s.headless, s.deep_delivery = self.limit.value(), self.headless.isChecked(), self.deep.isChecked()
        s.enabled_sites = [sid for sid, cb in self.site_checks.items() if cb.isChecked()]
        try:
            self.cfg.save()
        except OSError as e:
            self.log(f"Не удалось сохранить настройки: {e}")

    def _busy(self, busy: bool):
        for w in (self.btn_search, self.btn_import, self.query):
            w.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        self.progress.setVisible(busy)

    # ------------------------------------------------ поиск
    def search_one(self):
        q = self.query.text().strip()
        if q:
            self.start_search([q])

    def import_list(self):
        path, _ = QFileDialog.getOpenFileName(self, "Список позиций", "", "Списки (*.xlsx *.xlsm *.csv *.txt)")
        if not path:
            return
        try:
            queries = load_queries(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Импорт", f"Не удалось прочитать файл:\n{e}")
            return
        if not queries:
            QMessageBox.warning(self, "Импорт", "В файле не найдено позиций.")
            return
        preview = "\n".join(queries[:15]) + ("\n…" if len(queries) > 15 else "")
        if QMessageBox.question(self, "Импорт", f"Найдено позиций: {len(queries)}\n\n{preview}\n\nНачать поиск?") == QMessageBox.Yes:
            self.start_search(queries)

    def start_search(self, queries: list[str]):
        if self.worker and self.worker.isRunning():
            return
        sites = self.selected_sites()
        if not sites:
            QMessageBox.warning(self, "Поиск", "Отметьте хотя бы одну площадку.")
            return
        if self.setup_worker and self.setup_worker.isRunning():
            QMessageBox.information(self, "Поиск", "Сначала закройте окно браузера настройки.")
            return
        self._persist_options()
        self._busy(True)
        self.progress.setRange(0, len(queries) * len(sites)); self.progress.setValue(0)
        self.log(f"Старт: позиций {len(queries)}, площадок {len(sites)}")
        self.worker = SearchWorker(queries, sites, self.limit.value(), self.headless.isChecked(),
                                   self.deep.isChecked(), self.cfg.search.timeout_s)
        self.worker.log.connect(self.log)
        self.worker.found.connect(self.model.add)
        self.worker.progress.connect(lambda d, t: (self.progress.setValue(d), self.statusBar().showMessage(f"{d} из {t}")))
        self.worker.finished.connect(self._search_done)
        self.worker.start()

    def _search_done(self):
        self._busy(False)
        n = len(self.model.offers)
        self.statusBar().showMessage(f"Поиск завершён. Предложений в таблице: {n}")
        self.log(f"Готово. Всего предложений: {n}")

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.log("Останавливаю…")

    def open_link(self, idx):
        src = self.proxy.mapToSource(idx)
        webbrowser.open(self.model.offers[src.row()].url)

    # ------------------------------------------------ БД / экспорт
    def _rows(self, selected_only: bool) -> list[Offer]:
        if selected_only:
            rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
            return [self.model.offers[r] for r in sorted(rows)]
        return [self.model.offers[self.proxy.mapToSource(self.proxy.index(r, 0)).row()]
                for r in range(self.proxy.rowCount())]

    def save_db(self, selected_only: bool = False):
        offers = self._rows(selected_only)
        if not offers:
            QMessageBox.information(self, "БД", "Нет строк для сохранения.")
            return
        from .config import CONFIG_PATH
        if not CONFIG_PATH.exists() or not self.cfg.db.host:
            self.db_settings()
        self.btn_save.setEnabled(False); self.btn_save_sel.setEnabled(False)
        self.save_worker = SaveWorker(self.cfg.db, offers)
        self.save_worker.done.connect(lambda m: (self.log(m), self.statusBar().showMessage(m)))
        self.save_worker.failed.connect(lambda e: QMessageBox.critical(
            self, "БД", f"Ошибка сохранения:\n{e}\n\nПроверьте «Настройки → Подключение к PostgreSQL»."))
        self.save_worker.finished.connect(lambda: (self.btn_save.setEnabled(True), self.btn_save_sel.setEnabled(True)))
        self.save_worker.start()

    def export_excel(self):
        offers = self._rows(False)
        if not offers:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", f"сравнение_{datetime.now():%Y%m%d_%H%M}.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook(); ws = wb.active; ws.title = "Сравнение"
        ws.append(COLUMNS + ["Лучшая цена", "Быстрее всех"])
        for c in ws[1]:
            c.font = Font(bold=True)
        green, blue = PatternFill("solid", fgColor="D8F3DC"), PatternFill("solid", fgColor="DBEAFE")
        for o in offers:
            ws.append([o.query, o.marketplace, o.title, o.price, o.delivery_text, o.delivery_days,
                       o.delivery_date, o.url, "да" if o.is_best_price else "", "да" if o.is_fastest else ""])
            r = ws.max_row
            ws.cell(r, 8).hyperlink = o.url
            ws.cell(r, 8).font = Font(color="1D4ED8", underline="single")
            ws.cell(r, 7).number_format = "DD.MM.YYYY"
            ws.cell(r, 4).number_format = "# ##0.00"
            if o.is_best_price:
                ws.cell(r, 4).fill = green
            if o.is_fastest:
                ws.cell(r, 6).fill = blue
        for col, w in zip("ABCDEFGHIJ", (28, 20, 60, 12, 36, 7, 12, 50, 12, 12)):
            ws.column_dimensions[col].width = w
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"
        try:
            wb.save(path)
            self.log(f"Экспортировано: {path}")
        except OSError as e:
            QMessageBox.critical(self, "Экспорт", str(e))

    # ------------------------------------------------ настройки
    def db_settings(self):
        d = DbDialog(self.cfg.db, self)
        if d.exec():
            self.cfg.db = d.value()
            self._persist_options()
            self.log("Параметры БД сохранены")

    def setup_browser(self):
        if (self.worker and self.worker.isRunning()) or (self.setup_worker and self.setup_worker.isRunning()):
            return
        urls = [s.home for s in self.selected_sites() if s.home]
        self.setup_worker = SetupBrowserWorker(urls)
        self.setup_worker.log.connect(self.log)
        self.setup_worker.start()
        QMessageBox.information(self, "Браузер",
                                "Откроется окно браузера с площадками.\n\n"
                                "1) Выберите город/адрес доставки на каждой площадке.\n"
                                "2) При желании войдите в аккаунт.\n"
                                "3) Закройте окно браузера — настройки сохранятся.")

    def closeEvent(self, e):
        for w in (self.worker, self.setup_worker):
            if w and w.isRunning():
                w.stop()
                w.wait(8000)
        self._persist_options()
        super().closeEvent(e)


class BestFilterProxy(QSortFilterProxyModel):
    def __init__(self, only_best_cb: QCheckBox):
        super().__init__()
        self.only_best_cb = only_best_cb

    def filterAcceptsRow(self, row, parent):
        if self.only_best_cb.isChecked():
            o = self.sourceModel().offers[row]
            if not (o.is_best_price or o.is_fastest):
                return False
        return super().filterAcceptsRow(row, parent)


def run():
    import sys

    from .paths import data_dir

    logging.basicConfig(filename=str(data_dir() / "stroyagg.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8")
    sys.excepthook = lambda *a: log.error("".join(traceback.format_exception(*a)))
    app = QApplication(sys.argv)
    app.setApplicationName("StroyAgg")
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
