#!/usr/bin/env bash
# 复现 iOS 设备产物:把可移植核心(+SQLite 设备适配器)经 UniFFI 封为 MobileCore,
# 交叉编译 device + simulator 两个 arm64 静态库,生成 Swift 绑定,组装 XCFramework,
# 并(若有已启动模拟器)把冒烟测试 spawn 到模拟器实跑。
#
# 需:full Xcode(含 iPhoneOS / iPhoneSimulator SDK)、rustup 目标
#     aarch64-apple-ios 与 aarch64-apple-ios-sim。
#
# 用法:  agi-stack/scripts/build-ios.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.cargo/bin:$PATH"

CRATE="agistack-bindings-uniffi"
LIB="libagistack_mobile.a"
DEVICE_TARGET="aarch64-apple-ios"
SIM_TARGET="aarch64-apple-ios-sim"
SIM_TRIPLE="arm64-apple-ios18.0-simulator"   # swiftc 用 arm64(非 aarch64)三元组

echo "==> 确保 iOS rust 目标已安装"
rustup target add "$DEVICE_TARGET" "$SIM_TARGET" >/dev/null

echo "==> 交叉编译 device($DEVICE_TARGET)+ simulator($SIM_TARGET),release"
cargo build -p "$CRATE" --target "$DEVICE_TARGET" --release
cargo build -p "$CRATE" --target "$SIM_TARGET" --release

echo "==> 生成 Swift 绑定(用 host dylib 做元数据内省)"
cargo build -p "$CRATE" >/dev/null   # 产出 target/debug/libagistack_mobile.dylib
rm -rf target/uniffi-swift
cargo run -q -p "$CRATE" --bin uniffi-bindgen -- generate \
  --library target/debug/libagistack_mobile.dylib \
  --language swift --out-dir target/uniffi-swift

echo "==> 组装 XCFramework(device + simulator 两切片)"
rm -rf target/ios-headers target/AgistackMobile.xcframework
mkdir -p target/ios-headers
cp target/uniffi-swift/agistack_mobileFFI.h target/ios-headers/
cp target/uniffi-swift/agistack_mobileFFI.modulemap target/ios-headers/module.modulemap
xcodebuild -create-xcframework \
  -library "target/$DEVICE_TARGET/release/$LIB" -headers target/ios-headers \
  -library "target/$SIM_TARGET/release/$LIB" -headers target/ios-headers \
  -output target/AgistackMobile.xcframework

echo "==> 验证"
file "target/$DEVICE_TARGET/release/$LIB"
lipo -info "target/$DEVICE_TARGET/release/$LIB"
lipo -info "target/$SIM_TARGET/release/$LIB"
find target/AgistackMobile.xcframework -maxdepth 1 -type d

# 若有已启动模拟器,编译并实跑冒烟测试。
if xcrun simctl list devices booted 2>/dev/null | grep -q "(Booted)"; then
  echo "==> 检测到已启动模拟器,编译并 spawn 冒烟测试"
  mkdir -p target/smoke
  # Swift 仅允许名为 main.swift 的文件含顶层语句,故拷贝过去再编。
  cp scripts/ios-smoketest.swift target/smoke/main.swift
  xcrun --sdk iphonesimulator swiftc \
    -target "$SIM_TRIPLE" \
    -I target/ios-headers \
    -L "target/$SIM_TARGET/release" \
    -lagistack_mobile \
    target/uniffi-swift/agistack_mobile.swift \
    target/smoke/main.swift \
    -o target/smoke/smoketest
  xcrun simctl spawn booted target/smoke/smoketest
else
  echo "==> 无已启动模拟器,跳过实跑(可 'xcrun simctl boot <device>' 后重试)"
fi

echo "==> 完成。XCFramework: target/AgistackMobile.xcframework"
