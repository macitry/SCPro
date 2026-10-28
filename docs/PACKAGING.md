# 打包与发布

SCPro 的 Debian 打包信息在 `debian/` 下。构建规则只依赖 `dpkg-dev`，
不需要 `debhelper`，因此本地、GitHub Actions、Launchpad 都能直接构建。

## 本地构建 .deb

```bash
sudo apt install dpkg-dev fakeroot      # Ubuntu 通常已自带
dpkg-buildpackage -b -us -uc -d
ls ../scpro_*.deb
```

安装与卸载：

```bash
sudo apt install ./scpro_2.1.0_all.deb
scpro
sudo apt remove scpro        # 不会删除 ~/.config/scpro 等用户数据
```

包内容：

| 路径 | 说明 |
| --- | --- |
| `/usr/bin/scpro` | 启动器（设置 `PYTHONDONTWRITEBYTECODE`） |
| `/usr/share/scpro/` | 程序、Web UI、部署引擎与配置模板 |
| `/usr/share/applications/scpro.desktop` | 应用菜单入口 |
| `/usr/share/icons/hicolor/scalable/apps/scpro.svg` | 图标 |
| `/usr/share/man/man1/scpro.1.gz` | man page |
| `~/.config/scpro/` | 配置（首次运行时由模板生成） |
| `~/.local/state/scpro/logs/` | 日志，保留最近 30 份 |
| `~/.cache/scpro/` | 生成的图标与本地打包缓存 |

## 发布 GitHub Release

打一个 `v*` tag 即可，`.github/workflows/deb.yml` 会构建 `.deb` 并附到 Release：

```bash
git tag v2.1.0
git push origin v2.1.0
```

## 发布到 Ubuntu PPA

PPA 是 Ubuntu 的个人软件源，适合“任意 Ubuntu 用户一条命令安装”。

### 一次性准备

1. 注册 [Launchpad](https://launchpad.net/) 账号并签署 Ubuntu Code of Conduct；
2. 创建 GPG key 并上传到 Launchpad：
   ```bash
   gpg --full-generate-key
   gpg --list-secret-keys --keyid-format=long
   gpg --keyserver keyserver.ubuntu.com --send-keys <KEY_ID>
   ```
3. 在 Launchpad 的 “OpenPGP keys” 页面确认 key 已导入；
4. 安装上传工具：
   ```bash
   sudo apt install devscripts dput
   ```

### 创建 PPA 并上传

1. 打开 https://launchpad.net/~<你的用户名>/+activate-ppa 创建 PPA（示例名 `scpro`）；
2. **在名为 `scpro-2.1.0` 的干净目录里**构建源码包（Launchpad 要求 tar 顶层目录名匹配）：
   ```bash
   git clone https://github.com/macitry/SCPro.git /tmp/scpro-2.1.0
   cd /tmp/scpro-2.1.0
   debuild -S -k<KEY_ID>
   ```
   native 格式不需要额外的 orig tarball；`debian/source/options` 已排除本地配置、日志和缓存。
3. 上传：
   ```bash
   dput ppa:<你的用户名>/scpro ../scpro_2.1.0_source.changes
   ```
4. 在 Launchpad 页面等待构建完成（通常几分钟）。

### 用户安装

```bash
sudo add-apt-repository ppa:<你的用户名>/scpro
sudo apt update
sudo apt install scpro
```

### 多个 Ubuntu 版本

`debian/changelog` 第一行的 distribution 决定目标系列（当前是 `jammy`）。
要覆盖 24.04，把 `jammy` 改成 `noble` 并提升一个版本号后再上传，例如：

```bash
dch --distribution noble --newversion 2.0.1~noble1 "Build for noble"
```

## 关于官方源

官方 Debian/Ubuntu archive 还需要人工评审与 Debian Developer 赞助。当前包已经具备
基础条件：MIT 许可证、`debian/copyright`、FHS 合规（配置/日志/缓存全部走 XDG）。
剩余步骤是提交 ITP/RFS 并找到赞助者，周期以月计。
