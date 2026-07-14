# agi-stack — 逐平台构建矩阵(Wave K)
#
# 把已验证的每平台产物构建命令收敛为一键 target。设计原则:同一可移植核心
# (crates/core,零 tokio/std::time)编译/封装为各平台产物;每个 target 对应
# docs/architecture/09-shipping-matrix.md 的一行,并指向 04-spike-evidence 的证据。
#
# 用法:  make help        列出全部 target
#         make all         构建任意开发机皆可的产物(server/wasm/desktop)+ 测试
#         make ci          test + wasm-core(最小门禁,无需额外 SDK)
#
# 需额外 SDK 的 target(android 需 NDK、ios 需 full Xcode)单独显式调用。

export PATH := $(HOME)/.cargo/bin:$(PATH)

# ---- 可覆盖变量 ----
CARGO        ?= cargo
RUSTUP       ?= rustup
PNPM         ?= pnpm
PROFILE      ?= release
ADDR         ?= 127.0.0.1:8088
DESKTOP_APP_DIR ?= apps/desktop
DESKTOP_ICON_PNG ?= $(DESKTOP_APP_DIR)/src-tauri/icons/icon.png
DESKTOP_ICON_ICNS ?= $(DESKTOP_APP_DIR)/src-tauri/icons/icon.icns
PNPM_INSTALL_ARGS ?= --frozen-lockfile
# Android NDK(本机默认;生产建议 cargo-ndk)。覆盖:make android NDK=/path/to/ndk
NDK          ?= $(HOME)/Library/Android/sdk/ndk/30.0.14904198
ANDROID_TARGET ?= aarch64-linux-android
ANDROID_API    ?= 21
WASM_TARGET    ?= wasm32-unknown-unknown
WASM_OUT     ?= pkg
WASM_BROWSER_OUT ?= pkg-web
BENCH_REPORT ?= target/bench/scorecard.json
BENCH_BASELINE ?=
BENCH_REGRESSION_TOLERANCE_PCT ?= 20
TAURI_CLI ?= $(PNPM) dlx @tauri-apps/cli@2
TAURI_BUILD_ARGS ?=

UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
NDK_HOST_TAG ?= darwin-x86_64
else ifeq ($(UNAME_S),Linux)
NDK_HOST_TAG ?= linux-x86_64
else
NDK_HOST_TAG ?= linux-x86_64
endif

NDK_TC := $(NDK)/toolchains/llvm/prebuilt/$(NDK_HOST_TAG)/bin

.DEFAULT_GOAL := help
.PHONY: help test ci strangler-gate all ensure-wasm-target wasm-core server wasm-web desktop desktop-check desktop-deps desktop-frontend desktop-icons run-desktop desktop-bundle desktop-bundle-smoke android ios bench scorecard clean fmt-check

help: ## 列出全部 target
	@echo "agi-stack 构建矩阵 — target:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "矩阵详见 docs/architecture/09-shipping-matrix.md"

# ---- 跨平台门禁 ----
test: ## 整工作区测试(cargo test --workspace)
	$(CARGO) test --workspace

ensure-wasm-target: ## 安装核心 wasm 门禁所需 Rust target(幂等)
	$(RUSTUP) target add $(WASM_TARGET) >/dev/null

wasm-core: ensure-wasm-target ## 不变量:核心编为 wasm32-unknown-unknown(证运行时无关)
	$(CARGO) build -p agistack-core --target $(WASM_TARGET)

ci: test wasm-core ## 最小合并门禁:test + 核心 wasm32(无需额外 SDK)

strangler-gate: ## Strangler PR 门禁:fmt/clippy/test/wasm/parity/golden/gateway routing
	./scripts/check-strangler-gate.sh

# ---- 服务器 ----
server: ## 云端:原生 axum 服务器 release 二进制(~5.5 MB)
	$(CARGO) build -p agistack-server --profile $(PROFILE)
	@echo "==> 产物:target/$(PROFILE)/agistack-server"

run-server: ## 启动服务器(Rust 仅从仓库根目录 .env 读取 DATABASE_URL)
	AGISTACK_ADDR=$(ADDR) $(CARGO) run -p agistack-server

# ---- Web(浏览器 WASM) ----
wasm-web: ## Web:wasm-bindgen 浏览器包 + node 冒烟(core-as-guest,~124 KB)
	wasm-pack build crates/bindings-wasm --release --target nodejs --out-dir $(WASM_OUT)
	node crates/bindings-wasm/prepare-package.mjs $(WASM_OUT)
	node crates/bindings-wasm/smoke.cjs
	wasm-pack build crates/bindings-wasm --release --target web --out-dir $(WASM_BROWSER_OUT)
	node crates/bindings-wasm/prepare-package.mjs $(WASM_BROWSER_OUT)
	node crates/bindings-wasm/browser-smoke.mjs
	@echo "==> 产物:crates/bindings-wasm/$(WASM_OUT)/*.wasm + crates/bindings-wasm/$(WASM_BROWSER_OUT)/*.wasm"

# ---- PC 桌面(Tauri) ----
desktop: desktop-check desktop-bundle desktop-bundle-smoke ## 桌面:构建可安装 Tauri 客户端 bundle 并冒烟验证
	@echo "==> 桌面可安装客户端构建完成:$(DESKTOP_APP_DIR)/src-tauri/target/release/bundle/"

desktop-check: ## 桌面:Tauri 外壳全树编译 + 无头命令单测(故意排除出 workspace)
	cd $(DESKTOP_APP_DIR)/src-tauri && $(CARGO) build && $(CARGO) test
	@echo "==> 桌面外壳编译链接通过"

desktop-deps: ## 桌面:安装/校验前端依赖
	cd $(DESKTOP_APP_DIR) && CI=true $(PNPM) install $(PNPM_INSTALL_ARGS)

desktop-frontend: desktop-deps ## 桌面:构建 Tauri bundle 使用的前端 dist
	cd $(DESKTOP_APP_DIR) && $(PNPM) run build

desktop-icons: ## 桌面:生成 macOS bundle 所需 .icns 图标
	./scripts/build-desktop-icons.sh "$(DESKTOP_ICON_PNG)" "$(DESKTOP_ICON_ICNS)"

run-desktop: ## 启动桌面 App(Tauri dev 会拉起 Vite 并创建原生窗口)
	cd $(DESKTOP_APP_DIR) && $(TAURI_CLI) dev

desktop-bundle: desktop-frontend desktop-icons ## 桌面:完整 Tauri bundle(可安装客户端;CI macOS job 上传产物)
	cd $(DESKTOP_APP_DIR) && $(TAURI_CLI) build $(TAURI_BUILD_ARGS)
	@echo "==> 桌面 bundle:$(DESKTOP_APP_DIR)/src-tauri/target/release/bundle/"

desktop-bundle-smoke: ## 桌面:检查 Tauri bundle 产物目录、macOS .app 主二进制与标识
	./scripts/check-desktop-bundle.sh

# ---- 移动端:Android(需 NDK) ----
android: ## 移动:交叉编译真实 aarch64 Android .so + Kotlin 绑定(需 NDK)
	@test -d "$(NDK)" || { echo "ERROR: 未找到 NDK:$(NDK)(用 make android NDK=/path 覆盖)"; exit 1; }
	rustup target add $(ANDROID_TARGET) >/dev/null
	ANDROID_NDK_HOME="$(NDK)" ANDROID_NDK_ROOT="$(NDK)" \
	CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$(NDK_TC)/$(ANDROID_TARGET)$(ANDROID_API)-clang" \
	CC_aarch64_linux_android="$(NDK_TC)/$(ANDROID_TARGET)$(ANDROID_API)-clang" \
	AR_aarch64_linux_android="$(NDK_TC)/llvm-ar" \
	  $(CARGO) build -p agistack-bindings-uniffi --target $(ANDROID_TARGET) --release
	$(CARGO) build -p agistack-bindings-uniffi >/dev/null
	$(CARGO) run -q -p agistack-bindings-uniffi --bin uniffi-bindgen -- generate \
	  --library target/debug/libagistack_mobile.dylib --language kotlin --out-dir target/kotlin
	@file target/$(ANDROID_TARGET)/release/libagistack_mobile.so
	@echo "==> 产物:target/$(ANDROID_TARGET)/release/libagistack_mobile.so + target/kotlin/"

# ---- 移动端:iOS(需 full Xcode) ----
ios: ## 移动:device+sim 两 arm64 .a → XCFramework + Swift 绑定(需 full Xcode)
	./scripts/build-ios.sh
	@echo "==> 产物:target/AgistackMobile.xcframework"

# ---- 评分卡 ----
bench: ## go/no-go 评分卡(实测延迟 + 实读产物体积 → GO/NO-GO)
	AGISTACK_BENCH_REPORT="$(BENCH_REPORT)" \
	AGISTACK_BENCH_BASELINE="$(BENCH_BASELINE)" \
	AGISTACK_BENCH_REGRESSION_TOLERANCE_PCT="$(BENCH_REGRESSION_TOLERANCE_PCT)" \
	  $(CARGO) run -p agistack-bench --release

scorecard: bench ## bench 的别名

# ---- 任意开发机皆可的产物 ----
all: test wasm-core server wasm-web desktop bench ## 全部免额外 SDK 的产物 + 测试 + 评分卡
	@echo "==> all 完成(android/ios 需 NDK/Xcode,单独 make android / make ios)"

clean: ## 清理构建产物
	$(CARGO) clean
	rm -rf crates/bindings-wasm/$(WASM_OUT) crates/bindings-wasm/$(WASM_BROWSER_OUT) target/uniffi-swift target/kotlin \
	       target/ios-headers target/AgistackMobile.xcframework target/smoke
