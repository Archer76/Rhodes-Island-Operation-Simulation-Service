package main

import (
	"math"
	"testing"
)

// TestResolveDamageDodge 盯住 `resolveDamage` 的**闪避那一步**。
//
// 为什么单独写一条：闪避是"少算一层却照样出判决"的典型——24 例对拍语料里的干员
// 恰好都没有闪避，所以这个参数曾经整组不存在（原版三条打人路都在传它）。
// 单测把它钉在这里：次序（先防御/法抗、后闪避）、类型各取各的、真伤不吃。
func TestResolveDamageDodge(t *testing.T) {
	const near = 1e-9
	// ① 物理：500 攻 − 200 防 = 300，再折 25% 闪避 → 225
	if got := resolveDamage(500, "PHYSICAL", 1.0, 200, 0, 0.25); math.Abs(got-225) > near {
		t.Fatalf("物理闪避：期望 225，得到 %v", got)
	}
	// ② 法术：500 攻 × (1 − 0.2 法抗) = 400，再折 25% **法术**闪避 → 300
	if got := resolveDamage(500, "MAGIC", 1.0, 0, 20, 0.25); math.Abs(got-300) > near {
		t.Fatalf("法术闪避：期望 300，得到 %v", got)
	}
	// ③ 次序：闪避折的是**保底之后**的数（500 − 480 防 = 20 < 保底 25 → 25，
	//    再折 20% → 20）。先折闪避再判保底会得到 25，差的就是这个次序。
	if got := resolveDamage(500, "PHYSICAL", 1.0, 480, 0, 0.20); math.Abs(got-20) > near {
		t.Fatalf("保底与闪避的次序：期望 20，得到 %v", got)
	}
	// ④ 真实伤害不吃闪避（原版 damage.py:144）
	if got := resolveDamage(500, "TRUE", 1.0, 999, 999, 1.0); math.Abs(got-500) > near {
		t.Fatalf("真伤不该被闪避削：期望 500，得到 %v", got)
	}
	// ⑤ 闪避夹到 [0,1]：给 2.0 也只当 1.0（打不出负数伤害）
	if got := resolveDamage(500, "PHYSICAL", 1.0, 0, 0, 2.0); got != 0 {
		t.Fatalf("闪避超过 1 应当夹住：期望 0，得到 %v", got)
	}
}
