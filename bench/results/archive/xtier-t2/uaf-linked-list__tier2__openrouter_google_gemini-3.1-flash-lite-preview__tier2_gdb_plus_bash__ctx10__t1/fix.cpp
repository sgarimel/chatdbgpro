#include <cstdio>

struct Node {
    int value;
    Node *next;
};

/* Free every node in the list. */
static void destroy_list(Node *head) {
    Node *cur = head;
    while (cur != nullptr) {
        Node *next = cur->next;
        delete cur;
        cur = next;
    }
}

int main() {
    Node *c = new Node{3, nullptr};
    Node *b = new Node{2, c};
    Node *a = new Node{1, b};
    destroy_list(a);
    std::printf("done\n");
    return 0;
}
