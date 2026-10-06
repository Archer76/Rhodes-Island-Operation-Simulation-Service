package main

import "testing"

func TestRetreatRefundDescriptionExtraction(t *testing.T) {
	for _, tc := range []struct {
		description string
		want        bool
	}{
		{"撤退时返还初始部署费用", true},
		{"撤退时返还<@ba.kw>初始部署费用</>", true},
		{"击杀敌人后获得部署费用", false},
		{"", false},
	} {
		if got := isRetreatRefundDescription(tc.description); got != tc.want {
			t.Fatalf("description %q got %v want %v", tc.description, got, tc.want)
		}
		if got := textDerived(tc.description, nil).RetreatRefund; got != tc.want {
			t.Fatalf("textDerived %q got %v want %v", tc.description, got, tc.want)
		}
	}
}
