/*
 * proxy_udp_multiplayers.c — Advanced Multi-player UDP Proxy
 *
 * This version:
 * 1. Supports multiple destinations (routing by dest_ip:dest_port in JSON).
 * 2. Tags incoming packets with sender info: "[IP:PORT]JSON_DATA"
 *    This allows Python to track sequence numbers per sender.
 * 3. Handles packet sizes up to 64KB.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #include <windows.h>
    typedef SOCKET sock_t;
    #define SOCK_INVALID INVALID_SOCKET
    #define THREAD_CREATE(fn, arg) \
        do { HANDLE _h = CreateThread(NULL, 0, (fn), (arg), 0, NULL); if (_h) CloseHandle(_h); } while(0)
    #define THREAD_RET DWORD WINAPI
    #define THREAD_RETURN return 0
#else
    #include <sys/socket.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #include <pthread.h>
    typedef int sock_t;
    #define SOCK_INVALID (-1)
    #define THREAD_CREATE(fn, arg) \
        do { pthread_t _t; pthread_create(&_t, NULL, (fn), (arg)); pthread_detach(_t); } while(0)
    #define THREAD_RET void*
    #define THREAD_RETURN return NULL
#endif

#define BUFFER_SIZE 65535

static sock_t lan_sock = SOCK_INVALID;
static sock_t py_sock = SOCK_INVALID;
static struct sockaddr_in py_client_addr;
static int py_client_known = 0;
static int default_remote_port = 6000;

static void init_sockets(void) {
#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
#endif
}

static int get_field(const char* json, const char* field, char* out) {
    char search[64];
    sprintf(search, "\"%s\":", field);
    const char* p = strstr(json, search);
    if (!p) return 0;
    p += strlen(search);
    while (*p && (*p == ' ' || *p == '"' || *p == ':')) p++;
    int i = 0;
    while (*p && *p != '"' && *p != ',' && *p != '}' && i < 63) {
        out[i++] = *p++;
    }
    out[i] = '\0';
    return (i > 0);
}

static THREAD_RET lan_to_py_thread(void *arg) {
    char buffer[BUFFER_SIZE];
    char tagged_buffer[BUFFER_SIZE + 128];
    struct sockaddr_in sender;
    socklen_t slen = sizeof(sender);
    
    while (1) {
        int n = recvfrom(lan_sock, buffer, BUFFER_SIZE, 0, (struct sockaddr*)&sender, &slen);
        if (n > 0 && py_client_known) {
            char ip_str[64];
            inet_ntop(AF_INET, &sender.sin_addr, ip_str, sizeof(ip_str));
            int port = ntohs(sender.sin_port);
            
            // Tag message with sender info: "[IP:PORT]DATA"
            int tag_len = sprintf(tagged_buffer, "[%s:%d]", ip_str, port);
            memcpy(tagged_buffer + tag_len, buffer, n);
            
            sendto(py_sock, tagged_buffer, tag_len + n, 0, (struct sockaddr*)&py_client_addr, sizeof(py_client_addr));
        }
    }
    THREAD_RETURN;
}

static THREAD_RET py_to_lan_thread(void *arg) {
    char buffer[BUFFER_SIZE];
    struct sockaddr_in sender;
    socklen_t slen = sizeof(sender);
    
    while (1) {
        int n = recvfrom(py_sock, buffer, BUFFER_SIZE, 0, (struct sockaddr*)&sender, &slen);
        if (n <= 0) continue;
        
        if (!py_client_known) {
            py_client_addr = sender;
            py_client_known = 1;
            printf("[Proxy] Python app attached on port %d\n", ntohs(sender.sin_port));
        }
        
        char dest_ip[64], dest_port_str[64];
        if (get_field(buffer, "dest", dest_ip) && strcmp(dest_ip, "None") != 0) {
            int port = default_remote_port;
            if (get_field(buffer, "dest_port", dest_port_str) && strcmp(dest_port_str, "null") != 0) {
                port = atoi(dest_port_str);
            }
            
            struct sockaddr_in target;
            target.sin_family = AF_INET;
            target.sin_port = htons(port);
            target.sin_addr.s_addr = inet_addr(dest_ip);
            
            sendto(lan_sock, buffer, n, 0, (struct sockaddr*)&target, sizeof(target));
        }
    }
    THREAD_RETURN;
}

int main(int argc, char *argv[]) {
    int py_port = 5000, lan_port = 6000;
    if (argc >= 3) py_port = atoi(argv[2]);
    if (argc >= 4) lan_port = atoi(argv[3]);
    if (argc >= 5) default_remote_port = atoi(argv[4]);

    init_sockets();
    lan_sock = socket(AF_INET, SOCK_DGRAM, 0);
    py_sock = socket(AF_INET, SOCK_DGRAM, 0);
    
    struct sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(lan_port);
    if (bind(lan_sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        printf("[Proxy] Error binding LAN port %d\n", lan_port);
        return 1;
    }

    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    addr.sin_port = htons(py_port);
    if (bind(py_sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        printf("[Proxy] Error binding Python port %d\n", py_port);
        return 1;
    }

    printf("[Proxy] Advanced Multi-player Proxy Started.\n");
    printf("[Proxy] Listening on LAN:%d, IPC:%d, DefaultDestPort:%d\n", lan_port, py_port, default_remote_port);

    THREAD_CREATE(lan_to_py_thread, NULL);
    THREAD_CREATE(py_to_lan_thread, NULL);
    
    while (1) {
#ifdef _WIN32
        Sleep(1000);
#else
        sleep(1);
#endif
    }
    return 0;
}
