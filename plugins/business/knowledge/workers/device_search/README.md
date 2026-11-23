# Device knowledge retrieval

`search_documents` searches the text supplied for one operation and returns the ID, line number and excerpt of the first matching line per document. Results preserve document order and include at most 20 documents. The package needs the `tools.execute` permission.

Build this guest with the [knowledge package release](../../README.md). The linker reserves the first two Wasm pages for the request and result and places static data, stack and heap above them.

In desktop plugin settings, select the signed package, review its permissions and approve the installation. Run `search_documents` with an object such as the following.

```json
{
  "query": "设备",
  "documents": [
    {"id": "安装说明", "text": "第一步：登录。\n第二步：选择设备。"},
    {"id": "索引", "text": "本地知识库"}
  ]
}
```

With the `wasm32-unknown-unknown` Rust target and the repository Python environment installed, run `uv run python plugins/business/knowledge/workers/device_search/verify_sidecar.py` from the repository root. It builds a release, signs it with a temporary publisher key, and runs the Sidecar's cloud-device installation and invocation path against a local grant fixture. The test covers a 65,536-byte request, a 65,537-byte rejection and a signed future-only ABI range.
