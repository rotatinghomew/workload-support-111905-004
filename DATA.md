# 资料约定

原始资料均为本地合成。CSV 使用 UTF-8，首行是字段名。

`teams` 的 min_staff_min 是该网格在支援日期必须保留的同类能力分钟数。`shifts.team` 是提供人手的班组；`shifts.worker` 可关联投入。`loans` 记录人员从哪个团队支援哪个团队及实际生效分钟区间。`cases` 的 scene、steps、prereq 是受理时信息；opened 之后的 `activities` 有实际参与人员、记录归属和时间段。相同 visit 是同一次实际接触，允许多人参与。审核以 `adjudications` 的事实修正为准，conflict 记录涉及未裁工时，同人时间重叠不能重复计。`outcomes` 中 completed 是一次经确认的产出。`benchmarks` 给同类型、前置依赖和事前步骤档的可比分层，不是重量；比较用有效样本估计，不按写入多少活动给案件升档。
申请支援需同时超过 policy 对未结同类事项和可比投入差距的门槛；gap_min 是目标团队每个标准事项的投入缺口分钟数，min_cases 是参照和目标各自所需有效量。`pledges` 是已承诺但尚未开始（accepted）或已实际出勤（worked）的支援；source 是出人的网格，dest 是接收人手的网格。
