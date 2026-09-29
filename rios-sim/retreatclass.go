package main

// retreatclass.go：解算器要用的**撤退分类**（博士 2026-09-29 的三类口径）。
//
// 原文：「撤退只考虑三四星先锋和那几个快速复活干员，前者一般只用撤退一次，后者是
// 落地-自动开启技能-结束后马上撤退（麒麟R夜刀／焰狐龙梓兰）和落地-死亡（用于骗伤害的
// 砾和类似定位干员）。」
//
// 拆成三类：
//
//	① `ClassPioneerDP` —— 三四星**回费**先锋：撤一次把钱拿回来（至多一次）。
//	② `ClassFastSkill` —— 快速复活·技能型：落地 → 自动开技能 → 技能结束即撤。
//	③ `ClassFastBait`  —— 快速复活·骗伤型：落地 → 挨掉那一下 → 死亡（砾那一族）。
//
// 判据全部取自 `character_table.json`（Go 已经在读的那张表，见 `loadCharTable`）：
// 星级 `rarity`、职介 `profession`、子职业 `subProfessionId`、标签 `tagList`。
//
// ## 三条实测踩过的坑（都来自 `ak_tactic/team.py` 的记录，别重新发现）
//
//  1. **「快速复活」标签不能当判据**——它还挂着行商、情报官、傀儡师，甚至重射手
//     焰狐龙梓兰。**子职业**才是机制，标签只说明用途。所以②③两类的入口是
//     「子职业 `executor`」，只有那位非处决者的重射手走标签那条退路。
//  2. **处决者里还有机器人**：THRM-EX 是处决者、只要 3 费，但再部署 **200s**
//     ⇒ 只送得起一次。所以「能不能反复送」一律看**再部署时间**（真值已接，见
//     `docs/retreat-audit.md` §2.6），不看费用、也不看标签。
//  3. **「先锋基本都有回费」是统计不是定义**：46 名先锋里 43 名带「费用回复」，
//     判据走**标签**，不走职介名——但「三四星」这一半走 `rarity`。两半都要。
//
// ⚠ 送进来的 `redeployTime` 必须是**真值**（含潜能／天赋／模组）：焰狐龙梓兰裸装是
// 51s（不够格），挂上模组是 26s（够格）——同一名干员两种结论，差别只在这一列。

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
)

// RetreatClass 是一位干员在「撤退维度」上属于哪一类。
type RetreatClass int

const (
	//: 不进撤退维度：解算器不给它排撤退。
	ClassNone RetreatClass = iota
	//: ① 三四星回费先锋——撤一次把钱拿回来。
	ClassPioneerDP
	//: ② 快速复活·技能型——落地 → 开技能 → 技能结束即撤。
	ClassFastSkill
	//: ③ 快速复活·骗伤型——落地 → 挨那一下 → 死亡。
	ClassFastBait
)

func (c RetreatClass) String() string {
	switch c {
	case ClassPioneerDP:
		return "三四星回费先锋"
	case ClassFastSkill:
		return "快速复活·技能型"
	case ClassFastBait:
		return "快速复活·骗伤型"
	default:
		return "不进撤退维度"
	}
}

// fastRedeployMax 是「送得起第二次」的门槛（秒）。
//
// 与 `ak_tactic/team.py::BAIT_MAX_RESPAWN` 同值同理由：标准处决者 18s（弑君者 22s），
// THRM-EX 是 200s。设成「够用就行」而不是「越小越好」——再多一档就得另立判据了。
const fastRedeployMax = 30.0

// classTags 是判据用到的标签字面量（原版的 `tag_list` 里就是这几个词）。
const (
	tagDP        = "费用回复"
	tagFast      = "快速复活"
	tagProtect   = "防护"
	subExecutor  = "executor"
	profPioneer  = "PIONEER"
	rarityPrefix = "TIER_"
)

// charClassRow 是分类要用到的四个字段（`character_table.json` 里那一行的子集）。
type charClassRow struct {
	Rarity     string
	Profession string
	Sub        string
	Tags       []string
}

// loadCharClass 读一名干员的分类字段（走 `loadCharTable` 的包级缓存）。
func loadCharClass(charID string) (charClassRow, error) {
	tbl, err := loadCharTable()
	if err != nil {
		return charClassRow{}, err
	}
	raw, ok := tbl[charID]
	if !ok {
		return charClassRow{}, fmt.Errorf("character_table 里没有 %q", charID)
	}
	var row struct {
		Rarity     string   `json:"rarity"`
		Profession string   `json:"profession"`
		Sub        string   `json:"subProfessionId"`
		Tags       []string `json:"tagList"`
	}
	if err := json.Unmarshal(raw, &row); err != nil {
		return charClassRow{}, fmt.Errorf("%s 的分类字段解析失败：%w", charID, err)
	}
	return charClassRow{Rarity: row.Rarity, Profession: row.Profession,
		Sub: row.Sub, Tags: row.Tags}, nil
}

// tierOf 把 `TIER_4` 这样的星级字符串解成 4；认不得返回 0（**不猜**）。
func tierOf(rarity string) int {
	if !strings.HasPrefix(rarity, rarityPrefix) {
		return 0
	}
	n, err := strconv.Atoi(strings.TrimPrefix(rarity, rarityPrefix))
	if err != nil {
		return 0
	}
	return n
}

// hasTag 判标签里有没有这一个（原样比较，大小写敏感——表里就是中文）。
func hasTag(tags []string, want string) bool {
	for _, t := range tags {
		if t == want {
			return true
		}
	}
	return false
}

// retreatClassOf 判一位干员属于哪一类；三类都不进就是 `ClassNone`。
//
// `redeployTime` 必须是**真值**（含潜能／天赋／模组），`<= 0` 视为取不到 ⇒ 不进②③
// （宁可保守：拿不到再部署时间就不给排撤退，别排出一个游戏里做不到的打法）。
func retreatClassOf(charID string, redeployTime float64) (RetreatClass, error) {
	row, err := loadCharClass(charID)
	if err != nil {
		return ClassNone, err
	}
	//: ① 三四星**回费**先锋：星级 ＋ 职介 ＋ 标签，三样都要（见文件头第 3 条）。
	if t := tierOf(row.Rarity); (t == 3 || t == 4) &&
		row.Profession == profPioneer && hasTag(row.Tags, tagDP) {
		return ClassPioneerDP, nil
	}
	//: ②③ 先过「送得起第二次」这道门——**处决者也不例外**（THRM-EX 200s）。
	if redeployTime <= 0 || redeployTime > fastRedeployMax {
		return ClassNone, nil
	}
	if row.Sub == subExecutor {
		//: 骗伤型看**用途标签**（砾那一路是「防护」）；其余处决者（输出／爆发／控场）
		//: 都是「落地干活→撤」——控场那两位（红／卡夫卡）也走技能型，她们同样要开技能。
		if hasTag(row.Tags, tagProtect) {
			return ClassFastBait, nil
		}
		return ClassFastSkill, nil
	}
	//: 非处决者：只有挂着「快速复活」这一条退路（焰狐龙梓兰：重射手，靠天赋＋模组
	//: 把再部署压到门槛以下才进得来）。
	if hasTag(row.Tags, tagFast) {
		return ClassFastSkill, nil
	}
	return ClassNone, nil
}
