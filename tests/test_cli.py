import json

from idx.cli import main


def test_cli_import_find_ls_stats(data_root, export_zip, capsys):
    assert main(["import", str(export_zip)]) == 0
    out = capsys.readouterr().out
    assert "新規 7" in out and "追加 7" in out

    assert main(["find", "補助金", "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert len(hits) == 2 and {h["project"] for h in hits} == {"青空商店 Webリニューアル", "山川市 観光パンフレット"}

    assert main(["ls", "2222"]) == 0
    out = capsys.readouterr().out
    assert any(line.startswith("ci:project ") and line.endswith("= 山川市 観光パンフレット") for line in out.splitlines())

    assert main(["tag", "--no-finder", "2222", "+補助金", "-なし"]) == 0
    assert "tags: 補助金" in capsys.readouterr().out

    assert main(["query", "save", "補助金まわり", "補助金", "-tag:草案"]) == 0
    capsys.readouterr()
    assert main(["query", "run", "補助金まわり", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2

    assert main(["stats", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["items"] == 7

    assert main(["inspect", str(export_zip)]) == 0
    assert "chat_messages: list[" in capsys.readouterr().out


def test_cli_find_no_results(data_root, capsys):
    assert main(["find", "何もない"]) == 0
    assert "該当なし" in capsys.readouterr().out
