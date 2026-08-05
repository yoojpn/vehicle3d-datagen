#!/bin/bash
# 安全装置を先にバックグラウンドで起動してから、メイン処理を実行する
/workspace/repo/dataset_gen/safety_net_terminate.sh &
/workspace/repo/dataset_gen/budget_limited_run.sh
