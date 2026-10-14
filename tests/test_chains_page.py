import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from xrayui import i18n
from xrayui.core import chains
from xrayui.core.profiles import Profile
from xrayui.ui.pages.chains_page import ChainCard, ChainEditor, ChainsPage


def profiles():
    return [Profile(uid=f'h{i}', name=f'Hop {i}', protocol='vless', address='example.org',
                    id='11111111-1111-1111-1111-111111111111') for i in range(2)]


def test_editor_validation():
    app = QApplication.instance() or QApplication([])
    dialog = ChainEditor(profiles(), {})
    assert not dialog.save_button.isEnabled()
    dialog.available.setCurrentRow(0)
    dialog.add_hop()
    assert not dialog.save_button.isEnabled()
    dialog.available.setCurrentRow(1)
    dialog.add_hop()
    assert dialog.save_button.isEnabled()
    dialog.add_hop()
    assert not dialog.save_button.isEnabled()
    dialog.close()
    app.processEvents()


def test_page_reports_connect_and_rtl():
    app = QApplication.instance() or QApplication([])
    i18n.set_language('fa')
    try:
        page = ChainsPage()
        items = profiles()
        chain = chains.Chain(name='Route', hops=[p.uid for p in items])
        broken = chains.Chain(name='Broken', hops=chain.hops)
        page.set_chains([chain, broken], items, {
            chain.uid: {'verdict': 'OK', 'prefixes': [], 'country': 'de', 'exit_ip': '1.2.3.4'},
            broken.uid: {'verdict': 'BROKEN_AT', 'broken_at': 2, 'prefixes': []}})
        assert page.layoutDirection() == Qt.RightToLeft
        seen = []
        page.connectRequested.connect(seen.append)
        page.cards[0].connect_button.click()
        assert isinstance(seen[0], chains.ResolvedChain)
        assert seen[0].uid == chain.uid
        assert any('1.2.3.4' in label.text() for label in page.findChildren(QLabel))
        assert page.cards[1].broken_at == 2
        page.close()
    finally:
        i18n.set_language('en')
    app.processEvents()


def test_main_window_connects_resolved_chain(monkeypatch, tmp_path):
    from xrayui import paths
    from xrayui.ui.main_window import PAGE_CHAINS, MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(paths, 'base_dir', lambda: tmp_path)
    monkeypatch.setattr(paths, 'state_dir', lambda: tmp_path / 'state')
    monkeypatch.setattr(paths, 'profiles_dir', lambda: tmp_path / 'profiles')
    paths.ensure_dirs()
    window = MainWindow(elevated=False)
    try:
        items = profiles()
        for profile in items:
            window.store.save(profile)
        chain = chains.Chain(hops=[p.uid for p in items])
        window.chain_store.save(chain)
        window._reload_chains()
        window._show_page(PAGE_CHAINS)
        assert window._stack.currentWidget() is window.chains_page
        seen = []
        monkeypatch.setattr(window.conn, 'connect', seen.append)
        monkeypatch.setattr(window.conn, 'is_connected', lambda: False)
        monkeypatch.setattr(window, '_run_async', lambda work, done: work())
        window.chains_page.cards[0].connect_button.click()
        assert len(seen) == 1
        assert isinstance(seen[0], chains.ResolvedChain)
        assert [p.uid for p in seen[0].profiles] == chain.hops
    finally:
        window.close()
        app.processEvents()


def _preview_rows(lang, hop_count):
    i18n.set_language(lang)
    app = QApplication.instance() or QApplication([])
    items = [Profile(uid=f'h{i}', name=f'Hop {i}', protocol='vless', address='example.org',
                     id='11111111-1111-1111-1111-111111111111') for i in range(hop_count)]
    editor = ChainEditor(items, {}, chains.Chain(name='Route', hops=[p.uid for p in items]))
    editor.show()
    app.processEvents()
    view = editor.preview_host.itemAt(0).widget()
    rects = view.node_rects()
    editor.close()
    return {round(rect.top()) for rect in rects}, min(rect.width() for rect in rects), view.height()


@pytest.mark.parametrize('lang', ['en', 'fa'])
@pytest.mark.parametrize('hop_count', [3, 4])
def test_editor_preview_stays_on_one_row(lang, hop_count):
    try:
        rows, chip, height = _preview_rows(lang, hop_count)
    finally:
        i18n.set_language('en')
    assert len(rows) == 1
    assert chip >= 70
    assert height <= 120


def test_fa_metric_value_and_unit_share_one_line():
    # T1-FA-METRICS: the Persian download unit wrapped the tile onto two
    # lines. The fa tile unit stays short so value+unit fit on one line,
    # even with long values at a narrow card width.
    app = QApplication.instance() or QApplication([])
    i18n.set_language('fa')
    try:
        assert len(i18n.tr('Mbit/s')) <= 8, i18n.tr('Mbit/s')
        items = profiles()
        chain = chains.Chain(name='Route', hops=[p.uid for p in items])
        card = ChainCard(chain, items, {
            'warm_ms': 12345.0, 'cold_ms': 6789.0, 'download_mbps': 987.6,
            'verdict': 'OK', 'prefixes': []}, {})
        # Natural height: a forced taller card stretches the tiles and their
        # labels with it, which would fake a multi-line reading.
        card.resize(576, card.sizeHint().height())
        card.show()
        app.processEvents()
        units = [lab for lab in card.findChildren(QLabel)
                 if lab.objectName() == 'ChainUnit']
        assert len(units) == 3
        for unit in units:
            fm = unit.fontMetrics()
            assert unit.height() <= fm.lineSpacing() * 1.5, unit.text()
            assert fm.horizontalAdvance(unit.text()) <= unit.width(), unit.text()
        card.close()
        card.deleteLater()
    finally:
        i18n.set_language('en')
    app.processEvents()
