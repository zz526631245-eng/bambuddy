# Android 手机 App 交接说明

## 连接二维码（2026-08-12）

- 桌面端进入“设置 → 手机 App 连接”，二维码只编码服务器 HTTPS 地址，不包含账号、密码或 API 密钥；该二维码可以长期保留，换手机时重复扫描即可。
- Android App 首次打开时点击“扫描电脑二维码”，扫描桌面端二维码后会自动填入服务器地址，再点击“连接服务器”。也可以继续手动输入地址。
- 二维码中的地址不能是 `127.0.0.1` 或 `localhost`，应填写手机能访问的局域网 HTTPS 地址；电脑和手机需要在同一网络，并在首次使用时信任自签名证书。
- 当前可安装调试 APK：`frontend/android/app/build/outputs/apk/debug/app-debug.apk`。正式发布前仍需使用正式签名 keystore 生成 release APK。

## 分支与范围

- 分支：`codex/production-center-workspace`
- 入口：原前端路由 `/mobile`
- Android 工程：`frontend/android`
- Capacitor 配置：`frontend/capacitor.config.ts`

## 已完成

1. 手机首页使用大图标操作卡片：耗材入库、打印机换料、耗材用完、耗材报废、打印质检、清理料盘。
2. 换料向导强制先识别打印机 QR，再识别耗材 QR，并复用 `/api/v1/production/printer-consumables/scan` 的材料型号校验和旧耗材替换逻辑。
3. 入库/用完/报废复用耗材库扫码接口；质检/清板复用生产盘工作流接口，清板结果与桌面端同步。
4. `localStorage` 保存服务器地址，所有业务数据仍保存在桌面端 Bambuddy 服务器；API 客户端支持移动端跨主机地址。
5. 使用 Capacitor 8.5.0 封装 Android，申请相机和局域网访问权限，支持测试环境自签名证书/HTTP 局域网连接。

## 构建与测试

```powershell
cd frontend
npm.cmd run build
npx.cmd cap sync android
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot'
cd android
.\gradlew.bat assembleDebug
```

APK：`frontend/android/app/build/outputs/apk/debug/app-debug.apk`

前端构建和 Android Debug APK 已通过。完整 Vitest 有 6 项旧失败，详见 `docs/CURRENT_STATUS_CN.md`，不是移动端新增失败。

## 手机首次使用

1. 在电脑启动 Bambuddy，并确认电脑与手机处于同一局域网。
2. 安装 APK，打开后填写电脑可访问的地址，例如 `https://192.168.1.20:8019`。
3. 登录现有 Bambuddy 账号；进入首页后点击对应操作图标。
4. Android 系统提示相机权限时选择允许。

## 后续工作

- 用真实 Android 手机验收：HTTPS 证书信任、相机权限、登录、真实打印机 QR、耗材匹配错误提示、清板同步。
- 发布版需生成正式签名 keystore、替换应用图标/名称、关闭或限制 HTTP 明文访问，并按实际网络部署签发受信任 HTTPS 证书。
- 若需要扫码连续录入，可在当前向导上增加连续扫描模式；不改变后端幂等 operation_id 规则。
