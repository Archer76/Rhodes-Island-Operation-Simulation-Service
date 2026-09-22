package main

import "fmt"

// deploycost.go：面板里的**部署费用**（丙阶段四·第二十一批）。
//
// ## 为什么单独开一个出口
//
// `cost` 早就在 Go 的面板折算里算出来了，而且**已经被判据比过**——
// 干员判据比的是 `base` / `trust_bonus` / `potential_bonus` / `total`
// **四个整字典**（`check_operator_go.py` 的 679 次折算），
// 而 `cost` 就在那四个字典里。所以这里**没有**新建一份口径，
// 只是把同一个数**单独取出来**给 `deploys` 用。
//
// 取的是 `total`（`verify.py:320-325` 读的 `t` 就是它：`t.get("cost", 0)`）。
//
// ## 一处照抄原版的强制转换
//
// `int(t.get("cost", 0) or 0)`：`or 0` 让「键不在」与「值为 0」同义，
// 再取整。Go 侧 `applyRounding` 对整型属性已经给回整数，所以下面只在
// 类型不是整数时兜一次底——**形状不对要报错**，不许静默取 0。

// CostOf 取一名干员在其练度下的部署费用。
func CostOf(cfg OperatorCalcConfig) (int, error) {
	st, err := OperatorStatsFor(cfg, "round")
	if err != nil {
		return 0, err
	}
	v, ok := st.Total["cost"]
	if !ok {
		return 0, fmt.Errorf("面板 total 里没有 cost")
	}
	switch n := v.(type) {
	case int:
		return n, nil
	case float64:
		return int(n), nil
	}
	return 0, fmt.Errorf("cost 的类型不认识：%T", v)
}
