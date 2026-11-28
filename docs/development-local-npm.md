# 通过本机 npm 仓库分发签名业务包

本地 Verdaccio 提供 `http://127.0.0.1:4873`。仓库自带的发布工具先用当前开发环境公钥验证项目归档的签名。npm 负责存取，项目安装、授权、版本选择和回退仍走 MemStack API。registry 的 Docker 端口绑定到 IPv4 回环地址，配置里没有上游，容器使用具名卷保留制品。只有本地发布账号可以写入 `@memstack/*`。

在仓库根目录执行下列命令。把 `STANDARD_DIRECTORY` 指向已有的标准开发项目，它应包含 `publisher.pem` 和 `archives/`。

```sh
export STANDARD_DIRECTORY="$PWD/.memstack/standard"
uv run --locked python -m scripts.dev.npm_registry start
uv run --locked python -m scripts.dev.npm_registry publish --standard-directory "$STANDARD_DIRECTORY"
uv run --locked python -m scripts.dev.npm_registry verify --standard-directory "$STANDARD_DIRECTORY"
```

发布器从已签名清单取标识和版本。例如 `memstack-knowledge` 以 `@memstack/knowledge` 发布。每份 npm tarball 含 `package/package.json` 和原始的 `package/plugin.mspkg`。校验使用 npm CLI 从本地 registry 下载指定版本，对照 npm 元数据中的 SHA-512 校验整个 tarball，再逐字节比较内层归档与签名源文件。原版本再次发布时会校验现有内容；同一版本已存在另一份归档时会报错。修改业务后，请重新签发新版本。

可直接查看标准约定的任一包，或下载指定版本。

```sh
npm view @memstack/workspace versions --json --registry=http://127.0.0.1:4873
# 将 VERSION 替换为上一步显示的版本
npm pack @memstack/workspace@VERSION --registry=http://127.0.0.1:4873 --ignore-scripts
```

先启动 npm registry，再在标准项目中启用 npm 安装来源并启动服务。

```sh
touch "$STANDARD_DIRECTORY/npm-source.enabled"
MEMSTACK_DEV_PROFILE=standard make dev
```

也可对单次启动设置 `STANDARD_NPM_SOURCE=1`。标准 API 使用 Docker 内部地址 `http://npm-registry:4873`，通过独立网络 `memstack-plugin-npm` 访问 registry。宿主机运行的 API 可设置 `PACKAGE_NPM_REGISTRY_URL=http://127.0.0.1:4873`。登录后在精简 Web 的 `/plugins`、完整 Web 的租户插件市场或桌面的插件管理入口选择项目。初始六包仍可由标准启动流程直接从本地签名归档安装。

```sh
uv run --locked python -m scripts.dev.npm_registry restart
uv run --locked python -m scripts.dev.npm_registry verify --standard-directory "$STANDARD_DIRECTORY"
uv run --locked python -m scripts.dev.npm_registry stop
```

本地发布密码保存在权限为 0700 的 `.cache/plugin-npm/` 中，只有发布子进程的临时 npm 配置使用该凭据。调用者的 npm 登录配置不会被改写。停止和重启保留具名卷及本地账号。

## 从市场使用业务功能

在「发现」中按名称或包名搜索，打开卡片即可查看发行版本、适用端、签名摘要、业务页面、操作及所需权限。项目管理员选择「安装」，核对权限后批准启用。在详情中点击「打开功能」可进入已启用的页面，例如 Workspace 的目录和 CSV 导出。依赖本机能力的桌面操作还需在该设备批准当前摘要。

「已安装」显示当前项目的安装记录，「可更新」列出有新版的插件。更新前可查看权限变化，详情分别显示已选择版本和实际运行版本。点击「更多操作」可回退到上一运行版本，或在确认受影响的入口后卸载并保留项目数据。源离线时仍可查看项目已安装的记录。

包作者可在 `plugins/business/<包名>/market.json` 提供 `name`、`description` 的 `en` 和 `zh` 字段，以及 `icon` 图标标识。发布其他目录的业务包时，可通过 `--metadata-directory` 指定其父目录。发布器将展示信息写入 npm 元数据，从验签后的归档读取运行目标。旧包可以继续用包名浏览。
