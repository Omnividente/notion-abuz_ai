package main

import "fmt"

import "regexp"

func main() {
    cwdRe := regexp.MustCompile(`<cwd>([^<]+)</cwd>`)
    str := "<cwd>/hello</cwd>"
    match := cwdRe.FindStringSubmatch(str)
    fmt.Println(match)
}
