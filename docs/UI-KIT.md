# UI 底层规范（UI-KIT）

> 目标：所有页面由同一套组件拼出来；加页面=注册一条；改样式=改一处。

## 一、设计令牌（唯一来源：styles.css 的 :root）

```
颜色  --bg --panel --panel2 --line --line2 --fg --muted --faint
      --accent（橙 #ff6b00） --red --green
字号  --fs-xs 10 --fs-sm 11 --fs-md 13 --fs-lg 16 --fs-xl 20
行高  --lh-tight 1.3 --lh-base 1.6
间距  --sp-1 4 --sp-2 8 --sp-3 12 --sp-4 16 --sp-5 24 --sp-6 32
圆角  --r-0 0（默认直角） --r-sm 2
线    1px solid var(--line)
动效  --t-fast 120ms --t-base 200ms
```

**规则**：组件内不写字面色值、不写 px 间距，全部走令牌。

## 二、组件清单（ui_kit.js）

| 组件 | 签名 | 状态 |
|---|---|---|
| `Panel({title, hint, children})` | 容器 | 默认 / 折叠 |
| `Row({label, note, value, control})` | 一行 | 默认 / 禁用 |
| `Switch({checked, disabled, onChange})` | 开关 | on/off/disabled |
| `Bar({value, max, tone})` | 细条 4px | normal / warn / danger |
| `Stat({label, value, unit, delta})` | 数值卡 | 默认 / 上升 / 下降 |
| `Badge({text, tone})` | 小标签 | muted/accent/red/green |
| `Tabs({items, active, onChange})` | 标签栏 | 默认 / 滚动 |
| `Drawer({open, title, children, onClose})` | 抽屉 | open/closed |
| `Empty({text, action})` | 空状态 | 默认 / 带按钮 |
| `Timeline({items})` | 记录列表 | 默认 |
| `Grid({cols, children})` | 栅格 | 1/2/3 列自适应 |

## 三、页面注册表（registry.js）

```js
registerPage({
  id: 'now',                 // 唯一
  label: '她现在',
  group: 'main' | 'advanced',// 主导航 / 高级分组
  order: 20,
  icon: 'dot',               // 图标名（内置集合）
  data: ['status'],          // 需要拉取的接口
  render(ctx) { ... }        // 返回 DOM
})
```

导航由 registry 生成；**加页面只需要新增文件 + registerPage 一行**。

## 四、页面结构约定

```
顶部：一句人类语言状态（≤20 字）+ 一个进度条（可选）
中部：2–3 张卡（每张 ≤3 行）
底部：折叠区「详细数据」（原始字段、时间戳）
```

## 五、硬规则

1. 页面内不写颜色/间距字面量（走令牌）
2. 页面内不直接 fetch（走 ctx.data，注册表里声明）
3. 页面内不写导航（registry 统一生成）
4. 每页最多 3 张卡 + 1 个折叠区（信息层级）
5. 空数据必须显示 Empty，不显示 `—` 一排
6. 组件状态齐全：loading / empty / error 三态

## 六、迁移顺序

```
① ui_kit.js + registry.js 骨架（组件先做 6 个高频的）
② 新页（她现在 / 关系 / 记录）直接用 kit 写
③ 流水线页改造成 kit 组合
④ 老页面按需迁移（不强制）
```

## 七、验收

- `node --check` 全部通过
- guard + panel_html_check 通过
- 每个组件至少被一个页面使用（否则不抽）
- 截图：桌面 1440 / 手机 430 各一张
