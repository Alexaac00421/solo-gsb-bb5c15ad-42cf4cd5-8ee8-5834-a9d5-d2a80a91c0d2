#!/usr/bin/env bash
# 端到端演示：创建批次 → 节点 → 文物 → 读数（跨节点越界 + 缺测）→ 关闭事件 →
# 更正读数生成新版本 → 查看版本差异 → 查询跨文物共因风险组 → 离线采集包 →
# 运输节点交接（预览/确认/冻结）→ 监测标准校准（整套重评、标准快照、过期冲突）。
# 用法：BASE=http://localhost:8000 ./scripts/demo.sh
set -euo pipefail
BASE="${BASE:-http://localhost:8000}"
JSON='Content-Type: application/json'

echo "== 1. 创建批次 =="
curl -s -X POST "$BASE/api/batches" -H "$JSON" \
  -d '{"name":"2026 春季书画巡展","description":"本馆 → 巡展场馆"}'
echo

echo "== 2. 添加有序运输节点 =="
curl -s -X POST "$BASE/api/batches/1/nodes" -H "$JSON" -d '{"seq":1,"name":"库房","location":"本馆"}'
curl -s -X POST "$BASE/api/batches/1/nodes" -H "$JSON" -d '{"seq":2,"name":"运输车"}'
curl -s -X POST "$BASE/api/batches/1/nodes" -H "$JSON" -d '{"seq":3,"name":"展厅","location":"巡展场馆"}'
echo

echo "== 3. 登记文物（温湿度上下限 + 采样间隔 600 秒）=="
curl -s -X POST "$BASE/api/batches/1/artifacts" -H "$JSON" \
  -d '{"name":"青花瓷瓶","temp_min":18,"temp_max":24,"hum_min":45,"hum_max":60,"sample_interval":600}'
echo
curl -s -X POST "$BASE/api/batches/1/artifacts" -H "$JSON" \
  -d '{"name":"绢画","temp_min":18,"temp_max":24,"hum_min":45,"hum_max":60,"sample_interval":600}'
echo

echo "== 4. 提交读数：文物 1 温度跨节点连续越界后缺测；文物 2 在运输车同期越界 =="
curl -s -X POST "$BASE/api/batches/1/readings" -H "$JSON" -d '{
  "note": "首批数据",
  "readings": [
    {"artifact_id":1,"node_id":1,"ts":"2026-10-01T08:00:00Z","temperature":20,"humidity":50},
    {"artifact_id":1,"node_id":1,"ts":"2026-10-01T08:10:00Z","temperature":26,"humidity":50},
    {"artifact_id":1,"node_id":2,"ts":"2026-10-01T08:20:00Z","temperature":27,"humidity":50},
    {"artifact_id":1,"node_id":3,"ts":"2026-10-01T08:30:00Z","temperature":25,"humidity":50},
    {"artifact_id":1,"node_id":3,"ts":"2026-10-01T08:40:00Z","temperature":21,"humidity":50},
    {"artifact_id":1,"node_id":3,"ts":"2026-10-01T09:40:00Z","temperature":26,"humidity":50},
    {"artifact_id":1,"node_id":3,"ts":"2026-10-01T09:50:00Z","temperature":21,"humidity":50},
    {"artifact_id":2,"node_id":2,"ts":"2026-10-01T08:15:00Z","temperature":26,"humidity":50},
    {"artifact_id":2,"node_id":2,"ts":"2026-10-01T08:25:00Z","temperature":26,"humidity":50},
    {"artifact_id":2,"node_id":3,"ts":"2026-10-01T08:35:00Z","temperature":21,"humidity":50}
  ]}'
echo

echo "== 5. 校验拒绝示例：重复时间戳 / 非数值 / 无序上下限 =="
curl -s -X POST "$BASE/api/batches/1/readings" -H "$JSON" \
  -d '{"readings":[{"artifact_id":1,"node_id":1,"ts":"2026-10-01T08:00:00Z","temperature":20,"humidity":50}]}'
curl -s -X POST "$BASE/api/batches/1/readings" -H "$JSON" \
  -d '{"readings":[{"artifact_id":1,"node_id":1,"ts":"2026-10-01T10:00:00Z","temperature":"偏高","humidity":50}]}'
curl -s -X POST "$BASE/api/batches/1/artifacts" -H "$JSON" \
  -d '{"name":"错误示例","temp_min":30,"temp_max":10,"hum_min":45,"hum_max":60,"sample_interval":600}'
echo

echo "== 6. 关闭事件（须填写处置说明及证据编号）=="
EVENT_ID=$(curl -s "$BASE/api/batches/1/events?status=open" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')
curl -s -X POST "$BASE/api/events/$EVENT_ID/close" -H "$JSON" \
  -d '{"note":"已调整车厢温控并复查记录","evidence_no":"EV-2026-0001"}'
echo

echo "== 7. 更正读数 → 生成新评估版本（新版事件不继承关闭状态）=="
curl -s -X POST "$BASE/api/batches/1/readings" -H "$JSON" \
  -d '{"note":"更正运输车读数","readings":[{"artifact_id":1,"node_id":2,"ts":"2026-10-01T08:20:00Z","temperature":22,"humidity":50}]}'
echo

echo "== 8. 版本差异 v1 → v2 =="
curl -s "$BASE/api/batches/1/diff?from=1&to=2"
echo

echo "== 9. 批次风险摘要 =="
curl -s "$BASE/api/batches/1/summary"
echo

echo "== 10. 跨文物共因风险组：v1 文物1/文物2 在运输车同期温度越界（成组）；当前 v2 更正后共因消失 =="
echo "-- 当前版本（v2，更正后）--"
curl -s "$BASE/api/batches/1/risk-groups" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("当前版 v%d 组数: %d" % (d["version"], len(d["groups"])))'
echo "-- 历史版本 v1 --"
curl -s "$BASE/api/batches/1/risk-groups?version=1"
echo

echo "== 11. 旧版 v1 分组保持可查，关闭事件只更新计数（成员仍为 2 个事件）=="
curl -s "$BASE/api/batches/1/risk-groups?version=1" | python3 -c 'import json,sys; d=json.load(sys.stdin); g=d["groups"][0]; print("v1 组:", g["group_id"], g["metric_label"], "文物数", g["artifact_count"], "事件数", g["event_count"], "共有节点", [n["name"] for n in g["common_nodes"]], "开放/关闭", g["open_events"], "/", g["closed_events"])'

echo "== 12. 离线采集包：基准 v2（即当前版）上传 → 合并为 v3 =="
curl -s -X POST "$BASE/api/batches/1/packages" -H "$JSON" -d '{
  "package_id": "PKG-2026-0001",
  "base_version": 2,
  "note": "运输车离线采集回补",
  "readings": [
    {"artifact_id":1,"node_id":2,"ts":"2026-10-01T10:00:00Z","temperature":21,"humidity":50},
    {"artifact_id":1,"node_id":2,"ts":"2026-10-01T10:10:00Z","temperature":26,"humidity":50}
  ]}' | python3 -c 'import json,sys; d=json.load(sys.stdin); print("合并成功: 版本 v%d, 包 %s, 基准 v%d, 事件 %d 个" % (d["version"], d["package_id"], d["base_version"], len(d["events"])))'

echo "== 13. 相同内容重试 → 返回首次结果（deduplicated），不生成新版本 =="
curl -s -X POST "$BASE/api/batches/1/packages" -H "$JSON" -d '{
  "package_id": "PKG-2026-0001",
  "base_version": 2,
  "note": "运输车离线采集回补",
  "readings": [
    {"artifact_id":1,"node_id":2,"ts":"2026-10-01T10:00:00Z","temperature":21,"humidity":50},
    {"artifact_id":1,"node_id":2,"ts":"2026-10-01T10:10:00Z","temperature":26,"humidity":50}
  ]}' | python3 -c 'import json,sys; d=json.load(sys.stdin); print("重试: 版本 v%d, deduplicated=%s" % (d["version"], d["deduplicated"]))'

echo "== 14. 同编号不同内容 → 拒绝（409）=="
curl -s -X POST "$BASE/api/batches/1/packages" -H "$JSON" -d '{
  "package_id": "PKG-2026-0001",
  "base_version": 2,
  "note": "改动过的内容",
  "readings": [
    {"artifact_id":1,"node_id":2,"ts":"2026-10-01T11:00:00Z","temperature":21,"humidity":50}
  ]}'

echo "== 15. 过期基准冲突：base_version=1，而 08:20 读数已在 v2 被更正（27→22）→ 409 整包不写入 =="
curl -s -X POST "$BASE/api/batches/1/packages" -H "$JSON" -d '{
  "package_id": "PKG-2026-0002",
  "base_version": 1,
  "note": "基准过期的包",
  "readings": [
    {"artifact_id":1,"node_id":2,"ts":"2026-10-01T08:20:00Z","temperature":23,"humidity":50}
  ]}'

echo "== 16. 已成功接收的采集包列表（冲突/校验失败的包不占用编号）=="
curl -s "$BASE/api/batches/1/packages"
echo

echo "== 17. 运输节点交接：预览（库房 → 运输车 @ 08:15，按当前评估版本逐件核验）=="
PREVIEW=$(curl -s -X POST "$BASE/api/batches/1/handovers/preview" -H "$JSON" -d '{
  "prev_node_id": 1, "next_node_id": 2, "handover_ts": "2026-10-01T08:15:00Z"}')
echo "$PREVIEW" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("整体结论: %s（通过 %d / 待核 %d，基于 v%d）" % (d["result_label"], d["pass_count"], d["review_count"], d["version"])); [print("  - %s: %s｜%s" % (i["artifact_name"], i["status_label"], "；".join(i["reasons"]))) for i in d["items"]]'
TOKEN=$(echo "$PREVIEW" | python3 -c 'import json,sys; print(json.load(sys.stdin)["preview_token"])')
VER=$(echo "$PREVIEW" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')
echo

echo "== 18. 确认交接：有待核项须填写处置说明与证据编号 → 201 冻结记录 =="
curl -s -X POST "$BASE/api/batches/1/handovers" -H "$JSON" -d "{
  \"prev_node_id\": 1, \"next_node_id\": 2, \"handover_ts\": \"2026-10-01T08:15:00Z\",
  \"version\": $VER, \"preview_token\": \"$TOKEN\",
  \"note\": \"绢画前节点无读数，已现场复核并补采\", \"evidence_no\": \"EV-HO-0001\"}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("交接记录 #%d 已冻结: %s（v%d）" % (d["id"], d["result_label"], d["version"]))'
echo

echo "== 19. 补录读数生成新版本后，旧预览确认 → 409 要求重核 =="
curl -s -X POST "$BASE/api/batches/1/readings" -H "$JSON" \
  -d '{"note":"补录","readings":[{"artifact_id":2,"node_id":1,"ts":"2026-10-01T08:05:00Z","temperature":20,"humidity":50}]}' > /dev/null
curl -s -X POST "$BASE/api/batches/1/handovers" -H "$JSON" -d "{
  \"prev_node_id\": 1, \"next_node_id\": 2, \"handover_ts\": \"2026-10-01T08:15:00Z\",
  \"version\": $VER, \"preview_token\": \"$TOKEN\",
  \"note\": \"重试\", \"evidence_no\": \"EV-HO-0002\"}"
echo

echo "== 20. 交接记录列表与详情（确认后冻结，补录/更正/关闭事件均不改写）=="
curl -s "$BASE/api/batches/1/handovers"
curl -s "$BASE/api/batches/1/handovers/1" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("记录 #%d 冻结于 v%d: %s｜说明: %s｜证据: %s" % (d["id"], d["version"], d["result_label"], d["note"], d["evidence_no"]))'

echo
echo "== 21. 监测标准校准：文物 1 温度上限 24→22（以当前版为所见版本整套重评，生成新版本；新事件重新开放）=="
CUR_VER=$(curl -s "$BASE/api/batches/1/versions" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["version_no"])')
curl -s -X POST "$BASE/api/batches/1/calibrations" -H "$JSON" -d "{
  \"artifact_id\": 1,
  \"seen_version\": $CUR_VER,
  \"temp_min\": 18, \"temp_max\": 22, \"hum_min\": 45, \"hum_max\": 60,
  \"sample_interval\": 600,
  \"reason\": \"登记时温度上限录错，经计量室复核应为 22℃\"
}" | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d["calibration"]; print("校准成功: v%d → v%d（%s），温度上限 %g→%g；新版事件 %d 个（全部开放），缺测 %d 个，风险组 %d 组，读数仍为 %d 条" % (c["seen_version_no"], c["version_no"], c["artifact_name"], c["old_temp_max"], c["new_temp_max"], len(d["events"]), len(d["gaps"]), len(d["risk_groups"]), len(d["readings"])))'

echo
echo "== 22. 所见版本过期仍提交 → 409 要求重取；与当前标准相同 → 400 不产生版本 =="
curl -s -X POST "$BASE/api/batches/1/calibrations" -H "$JSON" -d "{
  \"artifact_id\": 1, \"seen_version\": $CUR_VER,
  \"temp_min\": 18, \"temp_max\": 20, \"hum_min\": 45, \"hum_max\": 60,
  \"sample_interval\": 600, \"reason\": \"用过期所见版本再次校准\"}"
echo
curl -s -X POST "$BASE/api/batches/1/calibrations" -H "$JSON" -d "{
  \"artifact_id\": 1, \"seen_version\": $((CUR_VER + 1)),
  \"temp_min\": 18, \"temp_max\": 22, \"hum_min\": 45, \"hum_max\": 60,
  \"sample_interval\": 600, \"reason\": \"与当前标准相同\"}"

echo
echo "== 23. 版本标准与校准记录查询（旧版旧标准可查，旧交接记录保持冻结）=="
curl -s "$BASE/api/batches/1/standards?version=$CUR_VER" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("v%d 标准快照:" % d["version"], [(s["artifact_name"], s["temp_max"], s["is_current"]) for s in d["standards"]])'
curl -s "$BASE/api/batches/1/calibrations" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("校准记录:", [(c["seen_version_no"], c["version_no"], c["artifact_name"]) for c in d])'
