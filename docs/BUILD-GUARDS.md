# 构建守卫（BUILD-GUARDS）

构建顺序：node scripts/inline-assets.mjs → node scripts/guard.mjs → 打包 → 部署。guard 失败即禁止产出/部署。

## 守卫清单
1. 面板必须位于 #view-settings 的 section 区间内（防止 append 到 </body> 后整页空白）
2. 标签与面板一一对应（data-settings-target ↔ settings-panel id，数量相等）
3. 文档骨架完整：单一 <!DOCTYPE、</body>、</html>，且 </html> 距文件末尾 ≤200 字符
4. 全页 id 唯一（剔除内联脚本/样式后统计）
5. _initStep('X', Y) 的 Y 必须有定义；window.XXX 赋值与引用一致（无 bare 引用）
6. 禁止未受存在性保护的 $('id').checked/value/textContent =（必须 setChecked/setText/setVal）
7. 内联幂等：连续两次 inline 产物 SHA1 相同

## 失败处置
- 面板越界：把面板 move 回 #view-settings section 内，不要用 append
- 重复 id：重命名并同步引用/测试
- 未定义常量/函数：在 app.js 顶层定义（需要跨作用域时挂 window 并统一引用）
- 危险赋值：改安全 setter
- 幂等失败：检查 inline-assets 是否从 index.src.html 读取（不要从 index.html）
