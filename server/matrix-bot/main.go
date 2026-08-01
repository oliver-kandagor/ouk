package main

import (
	"fmt"

	"maunium.net/go/mautrix"
)

func main() {
	fmt.Println("mautrix installed!")

	_ = mautrix.ReqLogin{}
}
