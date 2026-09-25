"""``idx`` コマンド。

    idx import <export.zip>        取り込み（mdimport）
    idx reindex [--full]           差分／全再索引（mdutil -E）
    idx find "<query>"             検索（mdfind）
    idx ls <file|id>               属性表示（mdls）
    idx tag <file> +協賛 -草案      タグ付け（Mac では Finder タグにも反映）
    idx note <file|id> ...         要点・決定事項・キーワードを書き込む
    idx query save|run|list|rm     保存クエリ＝スマートフォルダ
    idx stats                      件数・容量
    idx inspect <export.zip>       エクスポートの実キー名を確認する
    idx watch [--interval N]       任意起動の差分監視（常駐しない）
    idx suggest <prefix>           入力補完候補
    idx bridge ...                 Mac 連携（Finder タグ／保存検索）

出力は装飾なしの黒字テキストのみ。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, queries as saved
from .api import Index
from .ingest import import_source
from .paths import DataLayout
from .watch import reindex, watch


def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _fmt_hit(h: dict[str, Any], show_path: bool = True) -> str:
    date = (h.get("updated") or h.get("created") or "")[:10]
    head = "  ".join(x for x in [date, h.get("org") or "-", h.get("project") or "-", h.get("title") or ""] if x)
    lines = [head]
    if h.get("snippet"):
        lines.append(f"    {h['snippet']}")
    if h.get("url"):
        lines.append(f"    {h['url']}")
    if show_path and h.get("path"):
        lines.append(f"    {h['path']}")
    return "\n".join(lines)


def _print_hits(hits: list[dict[str, Any]], as_json: bool) -> None:
    if as_json:
        _print([_public_hit(h) for h in hits])
        return
    if not hits:
        print("該当なし")
        return
    for h in hits:
        print(_fmt_hit(h))
        print()


def _public_hit(h: dict[str, Any]) -> dict[str, Any]:
    keep = ["id", "kind", "title", "created", "updated", "project", "project_id", "org", "people", "tags",
            "summary", "decisions", "keywords", "source", "url", "turns", "recall_count", "path", "snippet", "score"]
    out = {k: h.get(k) for k in keep if k in h}
    out.update({k: v for k, v in h.items() if k.startswith("x_")})
    return out


# ---- 各サブコマンド -------------------------------------------------------------


def cmd_import(args, idx: Index) -> int:
    source = Path(args.source)
    if not source.exists():
        print(f"見つかりません: {source}", file=sys.stderr)
        return 2

    def progress(result, item):
        if args.verbose:
            print(f"{result:8s} {item.relpath}")

    report = import_source(source, idx.layout, idx.config, force=args.force, progress=progress)
    if not report.importers:
        print("このソースを扱えるインポータがありません（conversations.json / projects.json が見つかりません）", file=sys.stderr)
        return 2
    print(f"取り込み: 新規 {report.new} / 更新 {report.updated} / 変更なし {report.skipped}  （インポータ: {', '.join(report.importers)}）")
    if not args.no_reindex:
        r = reindex(idx.store, idx.layout)
        print(f"再索引: 追加 {r.added} / 更新 {r.updated} / 削除 {r.removed} / 変更なし {r.unchanged}")
        for e in r.errors:
            print(f"  エラー: {e}", file=sys.stderr)
    return 0


def cmd_reindex(args, idx: Index) -> int:
    def progress(kind, rel):
        if args.verbose:
            print(f"{kind:8s} {rel}")

    r = reindex(idx.store, idx.layout, full=args.full, progress=progress)
    print(f"再索引: 追加 {r.added} / 更新 {r.updated} / 削除 {r.removed} / 変更なし {r.unchanged}  （合計 {idx.store.count()} 件）")
    for e in r.errors:
        print(f"  エラー: {e}", file=sys.stderr)
    return 0


def _extract_query(tokens: list[str], args) -> str:
    """REMAINDER で受けた語列から既知のフラグ（--json / --semantic / -n N）を取り出し、残りをクエリにする。
    こうすることで "-tag:草案" のような除外指定をオプションと誤認しない。"""
    rest: list[str] = []
    it = iter(tokens)
    for tok in it:
        if tok == "--":
            rest.extend(it)
            break
        if tok == "--json":
            args.json = True
        elif tok == "--semantic":
            args.semantic = True
        elif tok in ("-n", "--limit"):
            try:
                args.limit = int(next(it))
            except (StopIteration, ValueError):
                pass
        elif tok.startswith("--limit="):
            args.limit = int(tok.split("=", 1)[1] or args.limit)
        else:
            rest.append(tok)
    return " ".join(rest)


def cmd_find(args, idx: Index) -> int:
    query = _extract_query(args.query, args)
    if not query.strip():
        print("検索語を指定してください", file=sys.stderr)
        return 2
    if args.semantic:
        from .semantic.hybrid import hybrid_find

        hits = hybrid_find(idx, query, limit=args.limit)
    else:
        hits = idx.find(query, limit=args.limit)
    _print_hits(hits, args.json)
    return 0


def cmd_ls(args, idx: Index) -> int:
    attrs = idx.ls(args.ref)
    if attrs is None:
        print(f"見つかりません: {args.ref}", file=sys.stderr)
        return 1
    if args.json:
        _print(attrs)
        return 0
    width = max(len(k) for k in attrs) + 3
    for k, v in attrs.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        elif isinstance(v, str) and "\n" in v:
            v = v.replace("\n", "\n" + " " * (width + 2))
        print(f"ci:{k}".ljust(width + 2) + f"= {v}")
    return 0


def cmd_cat(args, idx: Index) -> int:
    res = idx.read(args.ref)
    if res is None:
        print(f"見つかりません: {args.ref}", file=sys.stderr)
        return 1
    attrs, body = res
    if args.json:
        _print({"attrs": attrs, "body": body})
    else:
        print(body)
    return 0


def _split_tag_ops(ops: list[str]) -> tuple[list[str], list[str]]:
    add, remove = [], []
    for op in ops:
        if op.startswith("+"):
            add.append(op[1:])
        elif op.startswith("-"):
            remove.append(op[1:])
        else:
            add.append(op)
    return add, remove


def cmd_tag(args, idx: Index) -> int:
    ops = [o for o in args.ops if o != "--"]
    if not ops:
        print("タグ操作を指定してください（例: +協賛 -草案）", file=sys.stderr)
        return 2
    add, remove = _split_tag_ops(ops)
    attrs = idx.tag(args.ref, add, remove)
    if attrs is None:
        print(f"見つかりません: {args.ref}", file=sys.stderr)
        return 1
    print(f"tags: {', '.join(attrs['tags']) or '(なし)'}")
    if not args.no_finder:
        from .bridge.finder_tags import write_finder_tags

        p = idx.resolve_path(args.ref)
        if p is not None and write_finder_tags(p, attrs["tags"]):
            print("Finder タグにも反映しました")
    return 0


def cmd_note(args, idx: Index) -> int:
    changes: dict[str, Any] = {}
    if args.summary is not None:
        changes["summary"] = args.summary
    if args.decision:
        changes["decisions"] = args.decision
    if args.keyword:
        changes["keywords"] = args.keyword
    if args.tag:
        changes["tags"] = args.tag
    if args.people:
        changes["people"] = args.people
    if args.org is not None:
        changes["org"] = args.org
    if args.project is not None:
        changes["project"] = args.project
    if args.set:
        for kv in args.set:
            k, _, v = kv.partition("=")
            changes[k.strip()] = v
    attrs = idx.update_attrs(args.ref, changes, list_mode="replace" if args.replace else "merge")
    if attrs is None:
        print(f"見つかりません: {args.ref}", file=sys.stderr)
        return 1
    _print({k: attrs[k] for k in ("id", "title", "summary", "decisions", "keywords", "tags", "people", "org", "project", "path") if k in attrs})
    return 0


def cmd_query(args, idx: Index) -> int:
    if args.qcmd == "save":
        args.json = False
        args.semantic = False
        query_text = _extract_query(args.query, args)
        if not query_text.strip():
            print("クエリを指定してください", file=sys.stderr)
            return 2
        p = saved.save_query(idx.layout, args.name, query_text, args.description or "")
        print(f"保存しました: {p}")
        if args.saved_search:
            from .bridge.saved_search import install_saved_search

            out = install_saved_search(idx.layout, args.name, query_text)
            print(f"Finder 用スマートフォルダ: {out}" if out else "（Mac 以外なので .savedSearch は作りませんでした）")
        return 0
    if args.qcmd == "run":
        q = saved.load_query(idx.layout, args.name)
        if q is None:
            print(f"保存クエリがありません: {args.name}", file=sys.stderr)
            return 1
        _print_hits(idx.find(q["query"], limit=args.limit), args.json)
        return 0
    if args.qcmd == "list":
        items = saved.list_queries(idx.layout)
        if args.json:
            _print(items)
        elif not items:
            print("保存クエリはありません")
        else:
            for q in items:
                print(f"{q['name']}\t{q.get('query','')}")
        return 0
    if args.qcmd == "rm":
        p = saved.remove_query(idx.layout, args.name)
        print(f"_trash/ へ移しました: {p}" if p else f"保存クエリがありません: {args.name}")
        return 0 if p else 1
    return 2


def cmd_stats(args, idx: Index) -> int:
    st = idx.store.stats()
    st["data_dir"] = str(idx.layout.root)
    if args.json:
        _print(st)
        return 0
    print(f"データ置き場: {st['data_dir']}")
    print(f"索引件数: {st['items']}")
    print(f"本文文字数: {st['body_chars']:,}  索引DB: {st['db_bytes'] / 1024 / 1024:.1f} MB")
    for label, key in (("種別", "by_kind"), ("法人", "by_org"), ("プロジェクト", "by_project"), ("タグ", "tags")):
        if st.get(key):
            print(f"\n{label}:")
            for k, v in st[key].items():
                print(f"  {v:5d}  {k}")
    return 0


def cmd_inspect(args, idx: Index) -> int:
    from .importers._claude_common import load_json

    source = Path(args.source)
    for name in ("conversations.json", "projects.json", "users.json"):
        data = load_json(source, name)
        if data is None:
            print(f"{name}: なし")
            continue
        print(f"{name}: {type(data).__name__}, {len(data) if hasattr(data, '__len__') else '?'} 件")
        sample = data[0] if isinstance(data, list) and data else data
        if isinstance(sample, dict):
            for k, v in sample.items():
                desc = type(v).__name__
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    desc += f"[{', '.join(list(v[0].keys())[:12])}]"
                elif isinstance(v, dict):
                    desc += f"{{{', '.join(list(v.keys())[:12])}}}"
                elif isinstance(v, str):
                    desc += f' "{v[:40]}"' if len(v) <= 40 else f' "{v[:40]}…"'
                print(f"  {k}: {desc}")
        print()
    return 0


def cmd_watch(args, idx: Index) -> int:
    def on_change(r):
        print(f"再索引: 追加 {r.added} / 更新 {r.updated} / 削除 {r.removed}")

    print(f"{idx.layout.root} を {args.interval} 秒間隔で監視します（Ctrl+C で終了）")
    try:
        watch(idx.store, idx.layout, interval=args.interval, on_change=on_change)
    except KeyboardInterrupt:
        print("終了")
    return 0


def cmd_suggest(args, idx: Index) -> int:
    for s in idx.suggest(args.prefix, args.limit):
        print(s)
    return 0


def cmd_embed(args, idx: Index) -> int:
    from .semantic.embed import build_embeddings

    n = build_embeddings(idx, model_name=args.model, force=args.full, progress=print if args.verbose else None)
    print(f"埋め込み: {n} チャンクを更新")
    return 0


def cmd_bridge(args, idx: Index) -> int:
    if args.bcmd == "tags":
        from .bridge.finder_tags import sync_all_tags

        n = sync_all_tags(idx, direction=args.direction)
        print(f"Finder タグ同期 ({args.direction}): {n} ファイル")
        return 0
    if args.bcmd == "saved-search":
        from .bridge.saved_search import install_all_saved_searches

        outs = install_all_saved_searches(idx.layout)
        for o in outs:
            print(o)
        if not outs:
            print("（Mac 以外、または保存クエリがありません）")
        return 0
    return 2


# ---- 引数定義 -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="idx", description="étoile index: Claude の会話とプロジェクト資料を索引化して横断検索する")
    p.add_argument("--data", help="データ置き場（既定: $ETOILE_INDEX_DATA または ~/etoile-index-data）")
    p.add_argument("--version", action="version", version=f"idx {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import", help="エクスポート zip / ディレクトリを取り込む")
    s.add_argument("source")
    s.add_argument("--force", action="store_true", help="updated が同じでも上書きする")
    s.add_argument("--no-reindex", action="store_true", help="取り込み後に再索引しない")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("reindex", help="差分／全再索引")
    s.add_argument("--full", action="store_true", help="索引を捨てて全再構築")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_reindex)

    s = sub.add_parser("find", help="検索。例: idx find \"補助金 project:案件 -tag:草案\"")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.add_argument("--semantic", action="store_true", help="意味検索（埋め込み）を併用する")
    s.add_argument("query", nargs=argparse.REMAINDER, help="クエリ（-tag:x の除外もそのまま書ける）")
    s.set_defaults(func=cmd_find)

    s = sub.add_parser("ls", help="属性表示")
    s.add_argument("ref", help="ファイルパスまたは id")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_ls)

    s = sub.add_parser("cat", help="本文表示")
    s.add_argument("ref")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_cat)

    s = sub.add_parser("tag", help="タグ付け（+追加 -削除）。例: idx tag <file> +協賛 -草案")
    s.add_argument("--no-finder", action="store_true", help="Finder タグへ書き戻さない（ref より前に置く）")
    s.add_argument("ref")
    # "-草案" をオプションと誤認しないよう、ref 以降はすべてタグ操作として受け取る
    s.add_argument("ops", nargs=argparse.REMAINDER, help="+タグ / -タグ")
    s.set_defaults(func=cmd_tag)

    s = sub.add_parser("note", help="要点・決定事項・キーワード等を書き込む")
    s.add_argument("ref")
    s.add_argument("--summary")
    s.add_argument("--decision", action="append")
    s.add_argument("--keyword", action="append")
    s.add_argument("--tag", action="append")
    s.add_argument("--people", action="append")
    s.add_argument("--org")
    s.add_argument("--project")
    s.add_argument("--set", action="append", metavar="KEY=VALUE", help="任意の属性（拡張属性は x_ 付き）")
    s.add_argument("--replace", action="store_true", help="リスト属性を追記ではなく置換する")
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("query", help="保存クエリ（スマートフォルダ）")
    qs = s.add_subparsers(dest="qcmd", required=True)
    q = qs.add_parser("save")
    q.add_argument("--description")
    q.add_argument("--saved-search", action="store_true", help="Mac の Finder 用 .savedSearch も生成する（name より前に置く）")
    q.add_argument("name")
    q.add_argument("query", nargs=argparse.REMAINDER)
    q = qs.add_parser("run")
    q.add_argument("name")
    q.add_argument("-n", "--limit", type=int, default=20)
    q.add_argument("--json", action="store_true")
    q = qs.add_parser("list")
    q.add_argument("--json", action="store_true")
    q = qs.add_parser("rm")
    q.add_argument("name")
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("stats", help="件数・容量")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("inspect", help="エクスポートの実キー名を表示する")
    s.add_argument("source")
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser("watch", help="差分監視（任意起動・常駐しない）")
    s.add_argument("--interval", type=float, default=30.0)
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("suggest", help="入力補完候補")
    s.add_argument("prefix")
    s.add_argument("-n", "--limit", type=int, default=10)
    s.set_defaults(func=cmd_suggest)

    s = sub.add_parser("embed", help="意味検索用の埋め込みを作る（要 extras: semantic）")
    s.add_argument("--model", default=None)
    s.add_argument("--full", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_embed)

    s = sub.add_parser("bridge", help="Mac 連携")
    bs = s.add_subparsers(dest="bcmd", required=True)
    b = bs.add_parser("tags", help="ci:tags と Finder タグを同期")
    b.add_argument("--direction", choices=["to-finder", "from-finder"], default="to-finder")
    bs.add_parser("saved-search", help="queries/*.yaml から .savedSearch を生成")
    s.set_defaults(func=cmd_bridge)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    idx = Index(Path(args.data) if args.data else None)
    try:
        return int(args.func(args, idx) or 0)
    finally:
        idx.close()


if __name__ == "__main__":
    sys.exit(main())
