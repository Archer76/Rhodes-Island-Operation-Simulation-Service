// skillbind.go：把**一次部署绑的技能**算成 `(SkillSpec, Profile)` 两半。
//
// ## 口径（两条，都不是猜的）
//
//  1. **槽号**：计划里的 `deploys[*].skill` 是**技能槽号**（0–3）。按博士 2026-09-24 的
//     判定口径，**`0` 不等于「不用技能」**——除了一二星干员是真的没有技能之外，0 都会选到
//     **玩家的默认技能**；测试期间把 `0` 认定为 `1`。
//  2. **技能等级**：计划**不带** `skill_level`，按原版 `Deployment` 的默认值
//     **7**（`ak_tactic/frontend/schedule.py:66` 的 `skill_level: int = 7`）。
//     专精（`mastery`）是另一个独立入参，3★ 的技能只有 7 级、没有专精，先不接。
//
// ## 为什么两半分开算
//
// `SkillSpec` 是**时间怎么走**（技力、能不能开、多久结束——`skill.go` 的状态机读它），
// `Profile` 是**开着的时候数值是多少**（`sim.go` 在开/关那一刻整套换过去）。
// 数值那一半全部由 `skilleffects.go` 的**键表**算出来，本文件不写任何一条按键公式
// ——那是模块化的要害：加一名干员（不管几星）不需要动这里。
//
// ## 认不出来的键要去哪
//
// `bindSkillTo` 把**没认出来的黑板键**原样返回，调用方落进覆盖账
// （`OperatorsCoveredKeys` 那一族）。**静默忽略是不允许的**：那会把「没建」伪装成
// 「这个技能没有这条机制」。
package main

import (
	"fmt"
	"math"
)

// SkillLevelDefault 是计划不带 `skill_level` 时用的技能等级。
//
// 出处：`ak_tactic/frontend/schedule.py:66` 的 `skill_level: int = 7`。
const SkillLevelDefault = 7

// bindSkillTo 算出一名干员这次部署绑的技能的 (状态机, active 快照, 未识别键)。
//
// 三种「没有技能」都要**区分开**，不许压成一个 nil：
//
//	槽号缺省 0 但这位**一个技能槽都没有**（一二星／预备干员）⇒ 正常返回三个 nil；
//	槽号**越界**（例如写了 3 但这位只有 1 个技能）⇒ **报错**（静默截断会让
//	  规格里出现一个「看着有技能、其实绑错了」的干员）；
//	技能 id 取得到但 `SkillMetaFor` 取不到这一级 ⇒ 报错（数据缺口，不猜）。
func bindSkillTo(charID string, slot int, baseATK, baseDEF, baseRES, baseMaxHP,
	baseASPD, baseInterval float64, baseDamageType string) (*SkillSpec, *Profile,
	[]string, error) {
	if slot == 0 {
		//: ★ 博士口径：0 ＝ 默认技能 ＝ 技 1（一二星没有技能槽，下面 `len(ids)==0` 兜住）。
		slot = 1
	}
	ids, err := OperatorSkillIDs(charID)
	if err != nil {
		return nil, nil, nil, err
	}
	if len(ids) == 0 {
		return nil, nil, nil, nil
	}
	if slot < 1 || slot > len(ids) {
		return nil, nil, nil, fmt.Errorf(
			"%s 没有 %d 号技能槽（它有 %d 个：%v）——槽号越界**不截断**，"+
				"静默截断会让规格里出现一个绑错了技能的干员", charID, slot, len(ids), ids)
	}
	sid := ids[slot-1]
	meta, err := SkillMetaFor(sid, SkillLevelDefault)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("%s 的技能 %s 第 %d 级取不到：%w",
			charID, sid, SkillLevelDefault, err)
	}
	mods, unknown := ApplyBlackboard(meta.Blackboard)

	spec := &SkillSpec{
		SPType:       spTypeString(meta.SPType),
		Passive:      meta.SkillType == "PASSIVE",
		AutoTrigger:  meta.SkillType == "AUTO",
		SPCost:       meta.SPCost,
		InitSP:       meta.InitSP,
		Increment:    meta.Increment,
		MaxCharge:    int(math.Round(meta.MaxCharge)),
		DurationType: meta.DurationType,
		CostGain:     mods.CostGain,
		Duration:     0,
		Infinite:     meta.Duration == nil,
	}
	if meta.Duration != nil {
		spec.Duration = *meta.Duration
	}
	//: ⚠ `MaxCharge` 的缺省是 **1**（`skillmeta.go` 的注释：`or 1`）。
	//: 落成 0 会让「每秒回一次」变成「永不回」。
	if spec.MaxCharge < 1 {
		spec.MaxCharge = 1
	}

	//: ---- active 快照：**全部由键表算**，本文件不写任何一条按键公式 ----
	atk, def, maxHP, _, interval := applyMods(baseATK, baseDEF, baseMaxHP,
		baseASPD, baseInterval, mods)
	prof := &Profile{
		ATK:      atk,
		DEF:      def,
		RES:      baseRES,
		Interval: interval,
		//: ★ 伤害类型：**基准由特性决定**（博士 2026-09-24 口径：特性没写「法术伤害」
		//: 就一律物理），**技能正文写明「伤害类型变为 …」时按那句话切换**
		//: （`DamageTypeFromSkillText`：按短语、不按技能名 ⇒ 加一名干员不用改判定）。
		DamageType: DamageTypeFromSkillText(meta.Description, baseDamageType),
		MaxTarget:  1,
		AtkScale:   mods.AtkScale,
		HitCount:   mods.Times,
	}
	if mods.MaxHPPct != 0 {
		v := maxHP
		prof.MaxHP = &v
	}
	return spec, prof, unknown, nil
}

// spTypeString 把 `normalizeSPType` 的结果落成**规格要的字符串**。
//
// 它可能是字符串（数据里就是字符串），也可能是数字（`normalizeSPType` 对 spType==8
// 给了 "PASSIVE"，其余原样返回）。数字那一支按 `%v` 落成十进制串——**不猜它的语义**：
// 猜错会让状态机走岔，而规格里看不出来。
func spTypeString(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case nil:
		return ""
	default:
		return fmt.Sprintf("%v", t)
	}
}
