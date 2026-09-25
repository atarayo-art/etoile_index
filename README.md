# étoile index

Claude（claude.ai）の全スレッド・全プロジェクトを、Apple の Spotlight と同じ構造
（本体ファイル／メタデータ索引の分離、型別インポータ、タグ、スマートフォルダ、クエリ言語）で索引化し、
プロジェクトの壁を越えて全文＋意味で検索するツールです。
Claude 自身が索引を引いて答えられるように、MCP サーバとスキルを同梱しています。

- 日本語に強い部分一致（SQLite FTS5 の trigram トークナイザ。分かち書き不要）
- Markdown が唯一の真実。索引DBはいつでも捨てて再構築できる
- 常駐しない。cron 等の定期実行も登録しない
- ファイルは削除せず `_trash/` へ移す

## 構成（Spotlight との対応）

| Apple | étoile index |
|---|---|
| ファイル本体 | `threads/` 配下の Markdown（1スレッド＝1ファイル）と `projects/` 配下の資料 |
| `.Spotlight-V100/` | `.index/index.sqlite`（本体と分離。消しても再構築できる） |
| mds / mdworker | `idx reindex` / `idx watch`（mtime＋ハッシュで差分検出） |
| mdimporter | `idx/importers/` のプラグイン。`kind` ごとに1つ |
| UTI | `ci:kind`（`claude.thread` / `claude.project_doc` …） |
| `kMDItem*` | `ci:` 名前空間の属性（frontmatter と索引DBの列） |
| `mdls` / `mdfind` / `mdimport` | `idx ls` / `idx find` / `idx import` |
| Finder タグ | `ci:tags`。Mac では実ファイルの Finder タグにも書き戻す |
| スマートフォルダ | `queries/*.yaml`。Mac では `.savedSearch` も生成する |
| Core Spotlight の意味検索 | `idx find --semantic`（ローカル埋め込み＋RRF） |

```
etoile-index/
├── idx/                  パッケージ本体（CLI 名: idx）
│   ├── cli.py            idx コマンド
│   ├── store.py          SQLite（FTS5 trigram）
│   ├── schema.py         ci: 属性スキーマ
│   ├── query.py          クエリ言語パーサ
│   ├── rank.py           ランキング
│   ├── watch.py          差分検出（mds 相当）
│   ├── ingest.py         取り込み（Markdown 書き出し）
│   ├── importers/        mdimporter 相当（claude_export / claude_project_docs）
│   ├── semantic/         埋め込み＋ハイブリッド検索
│   ├── bridge/           Mac 連携（Finder タグ／保存検索）
│   └── mcp_server.py     MCP サーバ本体
├── mcp/server.py         MCP サーバ起動用ランチャ
├── skills/               Claude 用スキル（idx-recall / idx-index）
├── queries/              保存クエリの書式例
├── tests/                ダミー export によるテスト
└── plugin.json           プラグイン公開用マニフェスト
```

## データ置き場（利用者側）

既定は `~/etoile-index-data/`。環境変数 `ETOILE_INDEX_DATA` か `idx --data <dir>` で変更できます。

```
~/etoile-index-data/
├── threads/      YYYY/YYYY-MM-DD_<project-slug>_<title-slug>.md
├── projects/     <project-slug>/docs/*.md, instructions.md
├── queries/      *.yaml
├── config.yaml   法人の割り当て規則など（config.example.yaml を参照）
├── _trash/       削除の代わりにここへ移す
└── .index/       index.sqlite, embeddings.sqlite, state.json
```

ファイル名の区切りは `_` で、`|` `｜` は使いません。

## インストール

```
pipx install 'etoile-index[mcp]'         # 公開後
pip install -e '.[dev,mcp]'               # 開発時（このリポジトリで）
```

Python 3.11 以上、SQLite 3.34 以上（trigram トークナイザ）が必要です。

## 使い方

### 1. エクスポートを取り込む

claude.ai の 設定 → プライバシー → データをエクスポート で zip を取得します。

```
idx inspect ~/Downloads/data-2026-09-25.zip     # 実際のキー名を確認（形式は変わりうる）
idx import  ~/Downloads/data-2026-09-25.zip     # 取り込み＋差分再索引
```

- 1会話 → `threads/YYYY/….md`。本文は `## User` / `## Claude` の見出しで往復を並べます（時刻付き）。
- プロジェクトの指示文と添付資料 → `projects/<slug>/`。会話と同じ索引に入ります。
- 既存ファイルの `ci:updated` が同じなら上書きしません。上書きするときも、
  タグ・要点・決定事項・キーワード・法人・人物・参照回数は既存の値を保持します。

会話→プロジェクトの紐付けキーはエクスポートの版によって異なるため、
`project_uuid` / `project_id` / `project`（dict または文字列）を順に試します。
どれも無い場合は `config.yaml` の `project_overrides` で会話UUID→プロジェクト名を補えます。

### 2. 検索する

```
idx find "青空商店 補助金"                        # 全文（自由語は AND）
idx find "project:青空商店 tag:補助金"            # 属性で絞る
idx find "org:EXAMPLE-A after:2026-05-01 決定"     # 期間（created を対象）
idx find "people:田中さん kind:claude.thread"
idx find "補助金 -tag:草案 -下書き"                # 除外
idx find '"写真撮影費を補助金"'                    # 句
idx find --semantic "写真の費用を助成でまかなう"    # 意味検索（要 extras: semantic）
idx find --json -n 5 "補助金"                     # MCP 用の JSON
```

- フィールドは `ci:` 属性名（接頭辞なし）。別名: `tag`→`tags`, `keyword`/`kw`→`keywords`, `person`→`people`。
- `after:` / `before:` は `YYYY` / `YYYY-MM` / `YYYY-MM-DD` を受け付けます。
  `updated_after:` / `updated_before:` もあります。
- 3文字以上の語は trigram で部分一致します。2文字以下の語は LIKE で拾います。
- 結果は「日付 / 法人 / プロジェクト / タイトル / ヒット箇所 / URL / パス」で表示します。

### 3. 属性を見る・育てる

```
idx ls <file|id>                                 # 属性一覧（id は前方一致でも可）
idx cat <file|id>                                # 本文
idx tag <file|id> +協賛 -草案                     # タグ（Mac では Finder タグにも反映）
idx note <id> --summary "要点" --decision "決めたこと" --keyword 語 --tag 語
idx suggest 青                                    # 入力補完候補
idx stats                                        # 件数・容量
```

### 4. 保存クエリ（スマートフォルダ）

```
idx query save 補助金まわり "補助金 -tag:草案"
idx query run  補助金まわり
idx query list
idx query rm   補助金まわり                        # _trash/ へ移す
idx query save --saved-search 補助金まわり "補助金"   # Mac: Finder のサイドバー用も生成
```

### 5. 再索引

```
idx reindex            # 差分（mtime＋ハッシュ）
idx reindex --full     # 索引を捨てて全再構築
idx watch --interval 30   # 任意起動のポーリング。Ctrl+C で止める。常駐はしない
```

## 属性スキーマ（`ci:` 名前空間）

Markdown の先頭に YAML frontmatter として平文で保持します。索引DBにも同名の列があります。

```yaml
---
ci:id: "<会話UUID>"
ci:kind: "claude.thread"
ci:title: "青空商店 サイト刷新の方針整理"
ci:created: "2026-04-10T10:32:00+09:00"
ci:updated: "2026-04-10T11:05:00+09:00"
ci:project: "青空商店 Webリニューアル"
ci:project_id: "<projectUUID>"
ci:org: "EXAMPLE-A"
ci:people: [田中さん]
ci:tags: [Web, 設計]
ci:summary: "3行以内の要点"
ci:decisions: [トップページ最上部に営業時間を置く]
ci:keywords: [サイト刷新, 写真ギャラリー]
ci:source: "data-2026-09-25.zip"
ci:url: "https://claude.ai/chat/<uuid>"
ci:turns: 12
ci:recall_count: 0
---
```

- `summary` `decisions` `keywords` は取り込み時は空でよく、`idx note` か `idx-index` スキルで後から埋めます。
- 未知の属性は `ci:x_<name>` として受け入れます（`idx note --set x_foo=bar`、検索は `x_foo:bar`）。
- スキーマは `idx/schema.py` に一元定義しています。

## ランキング

FTS の bm25 を正規化した値に、次を加点します（`idx/rank.py`）。

- 鮮度: `ci:updated` からの経過日数で指数減衰（半減期 180 日）
- 利用頻度: `ci:recall_count`（Claude が `recall` で参照した回数）
- タグ一致: クエリ語がタグ／キーワードに完全一致した数

## 意味検索（フェーズ3）

```
pip install 'etoile-index[semantic]'
idx embed                      # 既定モデル intfloat/multilingual-e5-small でチャンク埋め込みを作る
idx find --semantic "言い換えた質問"
```

チャンクは往復単位（長ければ約500字で分割）。全文の順位と埋め込み類似度の順位を RRF で統合します。
属性フィルタ付きのクエリでは、全文側で通った文書だけを意味側でも採用します。
このリポジトリのテストは疑似埋め込みで RRF と差分更新だけを検証しており、実モデルでの精度は未検証です。

## Claude との接続（フェーズ2）

### MCP サーバ

```
idx-mcp                     # または python mcp/server.py（stdio）
```

tools: `search(query, limit, semantic)` / `recall(question, limit)` / `index_note(thread_id, summary, decisions, keywords, tags, people)` /
`ls(id)` / `read(id)` / `saved_queries()` / `run_saved_query(name)` / `suggest(prefix)` / `stats()`。
`recall` は参照したスレッドの `ci:recall_count` を加算します。

Claude Code / Claude Desktop の MCP 設定例:

```json
{
  "mcpServers": {
    "etoile-index": {
      "command": "idx-mcp",
      "env": { "ETOILE_INDEX_DATA": "/Users/<you>/etoile-index-data" }
    }
  }
}
```

PyPI の `mcp` パッケージは 1.x（FastMCP）と 2.x（MCPServer）の両方に対応しています。

### スキル

- `skills/idx-recall`: 「〇〇の経緯を思い出して」「前に決めた△△」で発火。`recall` を呼び、根拠のスレッド名と日付を添えて答える。
- `skills/idx-index`: スレッド末尾の「索引して」で発火。要点3行・決定事項・キーワード・タグを生成して `index_note` に渡す。

## Mac 連携（フェーズ4）

- `idx tag` は `ci:tags` を実ファイルの Finder タグ（`com.apple.metadata:_kMDItemUserTags`）にも書き戻します。
  `tag` コマンド（`brew install tag`）があればそれを使い、無ければ bplist を作って `xattr -wx` します。
- `idx bridge tags --direction from-finder` で Finder 側で付けたタグを frontmatter に取り込めます。
- `idx bridge saved-search` は `queries/*.yaml` から `~/Library/Saved Searches/*.savedSearch` を生成します。
  Spotlight のクエリ言語には全文・タグ・期間だけを写します（`project:` などは本文の全文一致で近似）。
- Spotlight が `.md` の本文を索引していない場合の確認:

```
mdimport -t -d2 ~/etoile-index-data/threads/2026/<file>.md | grep kMDItemTextContent
```

  出ないときは `/System/Library/Spotlight/RichText.mdimporter` を `~/Library/Spotlight/` に複製し、
  その `Info.plist` の `LSItemContentTypes` に `net.daringfireball.markdown` を追加して `mdimport -r` します。
  Mac 以外では bridge の機能はすべて何もしません。

## 新しいインポータを書く

`idx/importers/` にファイルを1つ足し、`Importer` を継承して `IMPORTER_CLASSES` に登録します。

```python
from idx.importers.base import Importer, Item

class ChatGPTExportImporter(Importer):
    kind = "chatgpt.thread"
    name = "chatgpt_export"

    def can_handle(self, source): ...
    def iter_items(self, source):
        yield Item(attrs={"id": ..., "kind": self.kind, "title": ..., "created": ..., "updated": ...},
                   body="## User\n...", relpath="threads/2026/2026-01-01_proj_title.md")
```

## 開発

```
pip install -e '.[dev,mcp]'
pytest
```

テストは `tests/fixtures/dummy_export/` の架空データ（架空の商店・自治体・人名）だけを使います。
実際のエクスポートや利用者データはリポジトリに入れません。

## ライセンス

MIT
