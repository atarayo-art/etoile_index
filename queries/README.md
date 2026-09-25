# queries/

保存クエリ（スマートフォルダ相当）の置き場。実際の保存先は利用者データ側の `~/etoile-index-data/queries/` で、
このディレクトリは書式の例だけを置く。

```yaml
name: 補助金まわり
query: 補助金 -tag:草案
description: 補助金に関わるスレッドを横断で一覧する
```

`idx query save <name> "<query>"` で作り、`idx query run <name>` で実行する。
Mac では `--saved-search` を付けると Finder のサイドバー用 `.savedSearch` も生成する。
