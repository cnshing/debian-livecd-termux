// Run against the patched LSP stdlib.cpp; compare its Android qsort_r fallback
// with std::sort, including context, duplicates, empty inputs and whole records.
#include <lsp-plug.in/stdlib/stdlib.h>
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <random>
#include <vector>

struct Item { int key; int id; unsigned char payload[7]; };

int compare(const void *a, const void *b, void *context) {
    const auto &left = *static_cast<const Item *>(a);
    const auto &right = *static_cast<const Item *>(b);
    return *static_cast<int *>(context) * ((left.key > right.key) - (left.key < right.key));
}

int main() {
    std::mt19937 random(1234);
    for (int direction : {-1, 1}) {
        for (unsigned count : {0, 1, 2, 3, 31, 256, 1001}) {
            std::vector<Item> items(count);
            for (unsigned i = 0; i < count; ++i) {
                items[i].key = random() % 13;
                items[i].id = i;
                for (auto &byte : items[i].payload) byte = i % 251;
            }
            auto expected = items;
            std::sort(expected.begin(), expected.end(), [&](auto &a, auto &b) {
                return direction * ((a.key > b.key) - (a.key < b.key)) < 0;
            });
            lsp::qsort_r(items.data(), items.size(), sizeof(Item), compare, &direction);
            for (unsigned i = 0; i < count; ++i) {
                assert(items[i].key == expected[i].key);
                for (auto byte : items[i].payload) assert(byte == items[i].id % 251);
            }
            std::sort(items.begin(), items.end(), [](auto &a, auto &b) { return a.id < b.id; });
            for (unsigned i = 0; i < count; ++i) assert(items[i].id == int(i));
        }
    }
    puts("Android qsort_r fallback: 14 cases passed");
}
