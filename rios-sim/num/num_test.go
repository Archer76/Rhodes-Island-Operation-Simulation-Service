package num

import (
	"bufio"
	"bytes"
	"math"
	"os"
	"strconv"
	"strings"
	"testing"
)

//: 夹具由 `out/acceptance/_hypot_rounding_check.py`（`decimal` 80 位真值）生成。
//: 它的三列是 `x y want`：`want` 是**正确舍入**的唯一答案。
const fixturePath = "testdata/hypot_rounding.txt"

//: 样本下限。夹具是「手挑 10 ＋ 标准库答错 721 ＋ 标准库答对 1500」拼的；
//: 少到这个数以下说明夹具被截断了（那是判据自己瞎，不是实现错）。
const fixtureMin = 2000

func readFixture(t *testing.T) [][3]float64 {
	t.Helper()
	raw, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatalf("读不到夹具 %s：%v（先用 out/acceptance/_hypot_rounding_check.py 生成）",
			fixturePath, err)
	}
	var out [][3]float64
	sc := bufio.NewScanner(bytes.NewReader(raw))
	sc.Buffer(make([]byte, 1<<16), 1<<16)
	ln := 0
	for sc.Scan() {
		ln++
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		f := strings.Fields(line)
		if len(f) != 3 {
			t.Fatalf("%s 第 %d 行不是三列：%q", fixturePath, ln, line)
		}
		var v [3]float64
		for i, s := range f {
			x, err := strconv.ParseFloat(s, 64)
			if err != nil {
				t.Fatalf("%s 第 %d 行第 %d 列解不开：%q", fixturePath, ln, i+1, s)
			}
			v[i] = x
		}
		if math.IsNaN(v[2]) || math.IsInf(v[2], 0) {
			t.Fatalf("%s 第 %d 行的期望值不是有限数：%v", fixturePath, ln, v[2])
		}
		out = append(out, v)
	}
	if err := sc.Err(); err != nil {
		t.Fatalf("读 %s 出错：%v", fixturePath, err)
	}
	return out
}

// TestHypotMatchesExactFixture 是**正确舍入**这条性质的棘轮：逐例要求逐位相等。
//
// ★ 它同时守两件事，缺一不算过：
//   - 本函数**一例都不许错**；
//   - 样本里**必须含有标准库答错的例**（否则这批样本没有行使到那处修复，
//     绿是零信息量的绿）。这一条是负对照，不是装饰。
func TestHypotMatchesExactFixture(t *testing.T) {
	cases := readFixture(t)
	if len(cases) < fixtureMin {
		t.Fatalf("夹具只有 %d 例（下限 %d）—— 夹具被截断了，先重新生成",
			len(cases), fixtureMin)
	}
	bad, stdlibWrong := 0, 0
	for i, c := range cases {
		if got := Hypot(c[0], c[1]); got != c[2] {
			bad++
			if bad <= 5 {
				t.Errorf("第 %d 例 Hypot(%.17g, %.17g) = %v，正确舍入值是 %v",
					i+1, c[0], c[1], got, c[2])
			}
		}
		if math.Hypot(c[0], c[1]) != c[2] {
			stdlibWrong++
		}
	}
	if bad != 0 {
		t.Errorf("Hypot 不正确 %d / %d 例（必须为 0）", bad, len(cases))
	}
	if stdlibWrong == 0 {
		t.Errorf("这批 %d 例里标准库一例都没答错 ⇒ 样本没有行使到那处修复，"+
			"这次绿是零信息量的绿（负对照不成立）", len(cases))
	}
	t.Logf("夹具 %d 例：Hypot 不正确 %d 例、标准库不正确 %d 例（负对照成立）",
		len(cases), bad, stdlibWrong)
}

// TestHypotSpecialValues 守「改这个函数不许改变特殊值行为」：逐条与 `math.Hypot` 比。
func TestHypotSpecialValues(t *testing.T) {
	inf, nan := math.Inf(1), math.NaN()
	cases := []struct{ x, y float64 }{
		{inf, 1}, {1, math.Inf(-1)}, {inf, inf}, {-inf, -inf},
		{nan, 1}, {1, nan}, {nan, nan},
		{nan, inf}, {inf, nan},
		{0, 0}, {math.Copysign(0, -1), math.Copysign(0, -1)}, {0, 7}, {9, 0},
	}
	for _, c := range cases {
		got, want := Hypot(c.x, c.y), math.Hypot(c.x, c.y)
		switch {
		case math.IsNaN(want):
			if !math.IsNaN(got) {
				t.Errorf("Hypot(%v, %v) = %v，标准库给 NaN ⇒ 也必须是 NaN", c.x, c.y, got)
			}
		case math.IsInf(want, 0):
			if !math.IsInf(got, 0) || math.Signbit(got) != math.Signbit(want) {
				t.Errorf("Hypot(%v, %v) = %v，标准库给 %v", c.x, c.y, got, want)
			}
		default:
			if got != want {
				t.Errorf("Hypot(%v, %v) = %v，标准库给 %v（这一档必须一致）",
					c.x, c.y, got, want)
			}
		}
	}
}

// TestHypotExactAndSymmetric：能精确的必须精确；交换两个参数必须同值。
func TestHypotExactAndSymmetric(t *testing.T) {
	for _, c := range []struct{ x, y, want float64 }{
		{3, 4, 5}, {5, 12, 13}, {8, 15, 17}, {0, 7, 7}, {9, 0, 9}, {1, 0, 1},
	} {
		if got := Hypot(c.x, c.y); got != c.want {
			t.Errorf("Hypot(%v, %v) = %v，应为 %v", c.x, c.y, got, c.want)
		}
	}
	for i, c := range readFixture(t) {
		if i >= 300 {
			break
		}
		if a, b := Hypot(c[0], c[1]), Hypot(c[1], c[0]); a != b {
			t.Fatalf("第 %d 例不对称：Hypot(x,y)=%v Hypot(y,x)=%v", i+1, a, b)
		}
	}
}
