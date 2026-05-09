int main(int argv,char **argc) {
    char buf[256];
    
    // Use strncpy to safely copy, ensuring null termination
    strncpy(buf, argc[1], sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = 0;
    return 0;
}
