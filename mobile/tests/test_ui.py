"""디자인 시스템과 화면 모듈: 세 디자인 × 라이트/다크에서 공용 위젯이 만들어지는가."""

import importlib
import pkgutil

import flet as ft
import pytest

import saipr.views
from saipr.core import fmt
from saipr.ui import widgets as w
from saipr.ui.theme import CUPERTINO, GLASS, MATERIAL, Design

DESIGNS = [(n, dark) for n in (GLASS, MATERIAL, CUPERTINO) for dark in (False, True)]


def test_all_views_import():
    for mod in pkgutil.iter_modules(saipr.views.__path__):
        importlib.import_module(f"saipr.views.{mod.name}")


@pytest.mark.parametrize(("name", "dark"), DESIGNS)
def test_design_builds_widgets(name, dark):
    d = Design(name, dark)
    book = {"id": 1, "title": "봄봄", "author": "김유정"}
    controls = [
        d.text("안녕", 15, "bold"), d.title("제목"), d.caption("설명"), d.card(ft.Text("x")), d.section("구역"),
        d.button("버튼", lambda e: None, icon=ft.Icons.ADD), d.chip("칩"), d.progress(0.4), d.divider(),
        d.backdrop(False), d.nav(0, lambda i: None, {}),
        w.cover(d, book, 96), w.avatar(d, {"id": 2, "nickname": "준호"}), w.ring(d, 0.5),
        w.stat(d, "3", "완독"), w.empty(d, ft.Icons.BOOK, "비었어요", "책을 담아 보세요"), w.pill(d, "잠김"),
    ]
    assert all(isinstance(c, ft.Control) for c in controls)


def test_keep_all_joins_syllables_but_not_words():
    out = fmt.keep_all("함께 읽어요")
    assert out.replace(fmt.WJ, "") == "함께 읽어요"
    assert out.split(" ")[0] == f"함{fmt.WJ}께"


def test_notification_links_map_to_screens():
    from saipr.app import link_target

    assert link_target("/rooms/3") == ("room", "3")
    assert link_target("/books/1/read?chunk=4") == ("read", "1")
    assert link_target("/books/7") == ("book", "7")
    assert link_target("/battles/2") == ("battle", "2")
    assert link_target("/teams/5") == ("team", "5")
    assert link_target("/me") == ("tab", "4")
    assert link_target(None) is None and link_target("https://evil") is None


def test_josa_ro():
    assert fmt.ro("서연") == "서연으로" and fmt.ro("준호") == "준호로" and fmt.ro("서울") == "서울로"
