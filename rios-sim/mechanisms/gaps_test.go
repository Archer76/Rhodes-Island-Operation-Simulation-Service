package mechanisms

import "testing"

func TestMergeIdentityAndOrdering(t *testing.T) {
	a := Gap{ID: "missing", Operator: "X", CharID: "char_x", SourceID: "skill_1", Key: "same", Instance: 0}
	b := a
	b.Instance = 1
	c := a
	c.SourceID = "skill_2"
	d := a
	d.Level = 8
	got := Merge([]Gap{a, b}, []Gap{a, c, d})
	if len(got) != 4 || got[0].Instance != 0 || got[1].Instance != 1 || got[2].SourceID != "skill_2" || got[3].Level != 8 {
		t.Fatalf("identity/order lost: %+v", got)
	}
}

func TestIncompleteErrorNamesSource(t *testing.T) {
	e := IncompleteError{Placeholders: []Gap{{Operator: "X", SourceName: "talent", Key: "prob", Reason: "not implemented"}}}
	if e.Error() == "" {
		t.Fatal("empty error")
	}
}
