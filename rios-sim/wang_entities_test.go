package main

import "testing"

func TestWangFieldConsumesOneAndResamplesStacks(t *testing.T) {
	var f wangStoneField
	a, _ := f.add("owner", Cell{1, 1}, false, 2)
	b, _ := f.add("owner", Cell{2, 1}, false, 2)
	c, _ := f.add("owner", Cell{3, 1}, true, 2)
	first, err := f.trigger(a, Cell{1, 1}, 2)
	if err != nil || first.Stacks != 3 || len(f.stones) != 2 {
		t.Fatalf("first %+v %v remaining%d", first, err, len(f.stones))
	}
	second, err := f.trigger(b, Cell{2, 1}, 2)
	if err != nil || second.Stacks != 2 || len(f.stones) != 1 {
		t.Fatalf("second %+v %v", second, err)
	}
	third, err := f.trigger(c, Cell{3, 1}, 2)
	if err != nil || third.Stacks != 1 {
		t.Fatalf("persistent S2 axis %+v %v", third, err)
	}
	if _, err = f.trigger(c, Cell{3, 1}, 2); err == nil {
		t.Fatal("consumed twice")
	}
}
func TestWangFieldDoesNotChainTriggerOrGuessTie(t *testing.T) {
	var f wangStoneField
	a, _ := f.add("owner", Cell{1, 1}, false, 3)
	f.add("owner", Cell{2, 1}, false, 3)
	got, err := f.trigger(a, Cell{2, 2}, 3)
	if err != nil || got.Stacks != 2 || len(f.stones) != 1 {
		t.Fatalf("S3 diagonal trigger %+v %v", got, err)
	}
	if len(f.stones) != 1 {
		t.Fatal("whole line consumed")
	}
	var g wangStoneField
	x, _ := g.add("owner", Cell{1, 1}, false, 1)
	g.add("owner", Cell{2, 1}, false, 1)
	if _, err = g.trigger(x, Cell{2, 2}, 1); err == nil {
		t.Fatal("S1 must require stepping on own cell")
	}
	if len(g.stones) != 2 {
		t.Fatal("rejected trigger changed state")
	}
}
func TestWangFieldOwnerCleanupAndOverlapRefusal(t *testing.T) {
	var f wangStoneField
	f.add("a", Cell{1, 1}, false, 1)
	f.add("b", Cell{2, 1}, true, 1)
	if f.stones[0].Activated || f.stones[1].Activated {
		t.Fatal("different owners connected")
	}
	if _, err := f.add("b", Cell{1, 1}, true, 1); err == nil {
		t.Fatal("unverified overlap silently accepted")
	}
	f.removeOwner("a")
	if len(f.stones) != 1 || f.stones[0].Owner != "b" {
		t.Fatal("owner cleanup")
	}
}
