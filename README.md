# 维修复验与部件追踪

本项目用于整理社区服务运营数据。`fixtures/` 保存本地合成源记录，各表字段和业务时序约定见 `DATA.md`。没有线上服务或真实个人信息。

使用 Python 3.11 验证资料结构：

```sh
python3 -m unittest discover -s tests -v
```
