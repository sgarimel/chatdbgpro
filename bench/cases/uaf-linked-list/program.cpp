#include <cstdio>

struct Node {
    int value;
    Node *next;
};

/* Free every node in the list. */
static void destroy_list(Node *head) {
    /* Walk from the head to the tail, deleting each node as we go.
     * Called when the owning container is destroyed. */
    for (Node *cur = head; cur != nullptr; cur = cur->next) {
        delete cur;
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
