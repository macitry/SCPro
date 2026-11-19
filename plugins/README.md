# SCPro 插件

一个插件就是一个目录，放进 `plugins/`（安装模式下也可放 `~/.config/scpro/plugins/`）即可，
不需要改主程序、不需要构建步骤。结构：

```
plugins/
└── mem-monitor/
    ├── plugin.json     # 元数据（必需）
    ├── plugin.py       # class Plugin（必需）
    └── panel.html      # webview 面板（可选）
```

## plugin.json

```json
{
  "id": "mem-monitor",
  "name": "内存监控",
  "name_en": "Memory Monitor",
  "version": "1.0.0",
  "description": "按应用统计整机内存占用，回收指定应用的文件缓存",
  "description_en": "Per-app memory usage and file-cache reclaim",
  "icon": "pulse",
  "entry": "plugin.py",
  "panel": "panel.html"
}
```

| 字段 | 说明 |
| --- | --- |
| `id` | 唯一标识，出现在 `plugin/<id>/<action>` 里，建议只用小写字母和 `-` |
| `name` / `name_en` | 中英文名称，用于活动栏图标提示和面板标题 |
| `icon` | codicon 名称，例如 `pulse`、`graph`、`database` |
| `entry` | Python 入口，默认 `plugin.py` |
| `panel` | 面板 HTML，相对插件目录；省略则不显示 webview |

## plugin.py

```python
from PyQt5.QtCore import QObject

class Plugin(QObject):
    def __init__(self, context):
        super().__init__()
        self.ctx = context

    def on_load(self):
        self.ctx.log("[INFO] hello")      # 写进主窗口的日志面板

    def handle(self, action, payload):     # 前端 plugin/<id>/<action>
        if action == "activate":
            self.ctx.ui("hello", {"ts": 1})  # 推事件给面板

    def on_unload(self):
        pass
```

`Plugin` 必须是 `QObject` 子类（宿主用 Qt 定时器/信号驱动它），构造函数只接收
`context`。插件运行在主进程里，可以直接 import 本目录的模块，也可以使用 PyQt5。

### context 提供的能力

| 成员 | 说明 |
| --- | --- |
| `ctx.ui(event, data)` | 向该插件的面板推一条事件 |
| `ctx.log(text)` | 写到主窗口「输出」面板并落盘 |
| `ctx.settings` / `ctx.save_settings({...})` | 插件私有设置，存 `plugin-data/<id>/settings.json` |
| `ctx.lang` | 当前界面语言 `zh` / `en` |
| `ctx.dir` / `ctx.app_dir` | 插件目录 / 程序目录 |
| `ctx.panel_url()` | 面板相对 URL |

## 面板（webview）

面板在 iframe 里运行，和主界面隔离：它拿不到主界面的 DOM，也不能直接调用 Python。
两边只通过消息通信，宿主负责转发。

**面板 → Python**

```js
parent.postMessage({__scpro: true, plugin: "mem-monitor",
                    action: "reclaim", data: {mbytes: 512}}, "*");
```

宿主会转成 `scpro://plugin/mem-monitor/reclaim?data=...`，最终进到
`Plugin.handle("reclaim", {...})`。

**Python → 面板**

```python
ctx.ui("snapshot", {...})       # 事件名 + 任意 JSON
```

面板侧：

```js
window.addEventListener("message", event => {
  const msg = event.data;
  if (!msg || msg.__scpro_event !== true) return;
  if (msg.event === "snapshot") render(msg.data);
});
```

宿主还会在面板加载和主题切换时推送 `theme` 事件，携带 `colors` / `dark` / `lang`，
面板照着设置 CSS 变量即可跟随 VS Code 主题。

## 约定

- 插件出错不会拖垮主程序：加载失败会记录到日志，命令处理异常会回推 `error` 事件。
- 面板首次加载时自己发 `activate`，宿主在打开/关闭时也会发一次 `activate`/`deactivate`，
  用来启停定时器——重复调用必须幂等。
- 耗时操作请放子线程，结果用 Qt 信号回主线程再 `ctx.ui()`；不要阻塞 UI。
- 插件目录的 `__pycache__`、`plugin-data` 不会被打进 deb 包。

## 内置插件：内存监控（mem-monitor）

- 数据来源：cgroup v2 的 `memory.current` / `memory.peak` / `memory.swap.current`，
  以及 `/proc/meminfo`；同名多进程（例如飞书 3 个进程）会合并成一条。
- 清理：往目标 cgroup 的 `memory.reclaim` 写 `512M` 之类的值，只回收该应用的**文件缓存**；
  直接写失败时依次尝试 `pkexec`（弹一次授权框）和 `sudo -n`。
- 整机清理：`sync` + `drop_caches`，需要 root。
- 刷新间隔 1/3/5/10 秒可选，配置存在 `plugin-data/mem-monitor/settings.json`。
- 口径说明：缓存卡片是 `/proc/meminfo` 的 `Cached + Buffers`（含 tmpfs、映射页、内核页）；
  表格里的「可回收」是各 cgroup `file - shmem - file_mapped - file_dirty`，只算能主动回收的
  干净页。两者本来就不相等：差值主要是 tmpfs、仍在映射的库文件、块设备 Buffers 和内核页。
  整机清理的预估释放量用 `Cached + Buffers - Shmem - Mapped` 计算，与实际相差不大。
