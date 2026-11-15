import ast
import os
import re

import pytest

from deepin_speedtest import i18n

PACKAGE = os.path.dirname(os.path.abspath(i18n.__file__))
PLACEHOLDER = re.compile(r"%(?:-?\d+)?(?:\.\d+)?[sdf]")


@pytest.mark.parametrize("env, expected", [
    ({}, "en"),
    ({"LANG": "en_US.UTF-8"}, "en"),
    ({"LANG": "es_ES.UTF-8"}, "es"),
    ({"LANG": "es_MX.UTF-8"}, "es"),
    ({"LANG": "es"}, "es"),
    ({"LANG": "C.UTF-8", "LANGUAGE": "es"}, "en"),
    ({"LANG": "en_US.UTF-8", "LANGUAGE": "es_ES:en"}, "es"),
    ({"LANG": "es_ES.UTF-8", "LANGUAGE": "en_US:es"}, "en"),
    ({"LANG": "en_US.UTF-8", "LC_MESSAGES": "es_AR.UTF-8"}, "es"),
    ({"LANG": "es_ES.UTF-8", "LC_ALL": "de_DE.UTF-8"}, "en"),
    ({"LANG": "et_EE.UTF-8"}, "en"),
    ({"LANG": "pt_BR.UTF-8"}, "en"),
])
def test_language_follows_the_system_locale(env, expected):
    assert i18n.detect_language(env) == expected


def test_english_is_the_default_and_unknown_texts_pass_through():
    assert i18n.tr("Start test") == "Start test"
    i18n.set_language("es")
    assert i18n.tr("Start test") == "Iniciar prueba"
    assert i18n.tr("some text a server sent") == "some text a server sent"
    assert i18n.tr("") == ""
    i18n.set_language("fr")
    assert i18n.language() == "en"


def _sources():
    for folder, _dirs, files in os.walk(PACKAGE):
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    yield path, ast.parse(handle.read())


def test_every_text_shown_to_the_user_has_a_spanish_translation():
    missing = []
    constants = {}
    for path, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" \
                    and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    text = arg.value
                elif isinstance(arg, ast.Name) and arg.id in constants:
                    text = constants[arg.id]
                else:
                    continue  # a run-time value, such as an engine message
                if text not in i18n.ES:
                    missing.append((os.path.basename(path), text[:60]))
    assert missing == []


def test_translations_keep_placeholders_links_and_markup():
    for english, spanish in i18n.ES.items():
        assert spanish.strip(), english
        assert PLACEHOLDER.findall(english) == PLACEHOLDER.findall(spanish), english
        assert english.count("%") == spanish.count("%"), english
        assert re.findall(r"https?://[^\s'\"<)]+", english) == re.findall(r"https?://[^\s'\"<)]+", spanish)
        assert sorted(re.findall(r"</?[a-z0-9]+", english)) == sorted(re.findall(r"</?[a-z0-9]+", spanish))
        assert english.endswith("\n") == spanish.endswith("\n"), english
        assert re.findall(r"--[a-z0-9-]+", english) == re.findall(r"--[a-z0-9-]+", spanish), english


def test_spanish_desktop_app(tmp_path, monkeypatch):
    pytest.importorskip("PyQt5.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QLabel
    from deepin_speedtest import app as appmod

    app = QApplication.instance() or QApplication([])
    i18n.set_language("es")
    window = appmod.MainWindow()
    try:
        assert window.start_btn.text() == "Iniciar prueba"
        assert [b.text() for b in window.nav_group.buttons()] == ["Prueba de velocidad", "Historial"]
        assert window.card_down.title.text() == "DESCARGA"
        assert "automático" in window.server_combo.itemText(0)
        window._handle_event({"type": "error", "message": "The server stopped responding."})
        assert window.status.text() == "El servidor dejó de responder."
        window._handle_event({"type": "error", "message": "Connection refused"})
        assert window.status.text() == "Connection refused"

        about = appmod.AboutDialog(window._sandbox_text(), window)
        assert about.tabs.tabText(0) == "Acerca de" and about.tabs.tabText(1) == "Créditos"
        text = about.tabs.widget(0).findChildren(QLabel)[0].text()
        assert ('Creado por Eli Linares para <a href="https://xn--deepinenespaol-1nb.org">'
                'https://deepinenespañol.org</a>') in text
        assert about.findChild(QDialogButtonBox).button(QDialogButtonBox.Close).text() == "Cerrar"

        options = appmod.OptionsDialog("mlab", 1000, window)
        assert options.windowTitle() == "Opciones"
        assert options.speed.itemText(2) == "Hasta 5 Gbit/s"
        buttons = options.findChild(QDialogButtonBox)
        assert buttons.button(QDialogButtonBox.Ok).text() == "Aceptar"
        assert buttons.button(QDialogButtonBox.Cancel).text() == "Cancelar"

        add = appmod.AddServerDialog(window)
        add.address.setText("http://x.example.org")
        add._accept()
        assert add.error.text() == "Solo se permiten servidores https:// o wss://."
    finally:
        window.close()
        app.processEvents()


def test_spanish_terminal_help(capsys):
    from deepin_speedtest import cli
    i18n.set_language("es")
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "usar un servidor ndt7 propio" in out
