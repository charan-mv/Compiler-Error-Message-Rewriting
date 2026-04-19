namespace std {
    struct dummy_stream {
        template <typename T>
        dummy_stream& operator<<(const T&) { return *this; }
        template <typename T>
        dummy_stream& operator>>(T&) { return *this; }
    };
    extern dummy_stream cout;
    extern dummy_stream cin;
    extern dummy_stream cerr;
    extern dummy_stream endl;
    class string {};
}
using namespace std;

#line 1 "input.cpp"
int main() {
    using namespace std;
    cout<<"hello world";
    return 0;
}
