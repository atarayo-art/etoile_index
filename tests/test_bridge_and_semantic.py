import plistlib

from idx.bridge.finder_tags import decode_tags, encode_tags
from idx.bridge.saved_search import build_saved_search, install_saved_search, to_spotlight_query
from idx.paths import DataLayout
from idx.semantic.embed import Embedder, build_embeddings, split_chunks
from idx.semantic.hybrid import hybrid_find, rrf


def test_finder_tag_plist_roundtrip():
    blob = encode_tags(["補助金", "写真"])
    assert plistlib.loads(blob) == ["補助金", "写真"]
    assert decode_tags(plistlib.dumps(["赤\n6", "青"], fmt=plistlib.FMT_BINARY)) == ["赤", "青"]


def test_spotlight_query_translation():
    q = to_spotlight_query('補助金 tag:写真 -tag:草案 after:2026-05-01')
    assert 'kMDItemTextContent == "*補助金*"cd' in q
    assert 'kMDItemUserTags == "写真"cd' in q and '!(kMDItemUserTags == "草案"cd)' in q
    assert "kMDItemContentCreationDate >= $time.iso(2026-05-01T00:00:00Z)" in q


def test_saved_search_file(tmp_path):
    layout = DataLayout(tmp_path / "data")
    out = install_saved_search(layout, "補助金まわり", "補助金", dest_dir=tmp_path / "ss")
    assert out.name == "補助金まわり.savedSearch"
    d = plistlib.loads(out.read_bytes())
    assert d["RawQueryDict"]["SearchScopes"] == [str(layout.root)]
    assert d["RawQuery"] == build_saved_search("x", "補助金", layout.root)["RawQuery"]


def test_split_chunks():
    body = "## User\n" + "あ" * 1200 + "\n## Claude\n短い\n"
    chunks = split_chunks(body, max_chars=500)
    assert len(chunks) == 4 and chunks[-1] == "Claude\n短い"


def test_rrf():
    s = rrf([["a", "b"], ["b", "c"]])
    assert s["b"] > s["a"] > s["c"] > 0


def _fake_encode(texts):
    # 決定的な疑似埋め込み: 語彙の有無をベクトルにする（言い換えを模擬するため同義語を同じ次元に）
    vocab = ["写真", "撮影", "補助金", "助成", "旅行", "観光", "サイト", "刷新"]
    syn = {"助成": "補助金", "撮影": "写真"}
    out = []
    for t in texts:
        v = [0.0] * len(vocab)
        for i, w in enumerate(vocab):
            if w in t:
                v[vocab.index(syn.get(w, w))] += 1.0
        out.append(v)
    return out


def test_hybrid_find_with_fake_embedder(index):
    emb = Embedder(encode=_fake_encode)
    n = build_embeddings(index, embedder=emb)
    assert n > 0
    # 「助成」は本文に無いが、疑似埋め込みでは「補助金」と同義なので意味側で当たる
    hits = hybrid_find(index, "助成 撮影 サイト", limit=3, embedder=emb)
    assert hits and hits[0]["title"] == "青空商店 補助金で写真撮影をまかなえるか"
    # 2回目は差分なしで 0
    assert build_embeddings(index, embedder=emb) == 0
