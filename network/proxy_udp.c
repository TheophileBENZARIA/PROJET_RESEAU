/*
 * proxy_udp.c - Proxy UDP P2P (multi-threads)
 *
 * Architecture 100% UDP, sans connexion.
 * - 1 socket UDP local (port Python)
 * - 1 socket UDP LAN (port reseau)
 * - Thread 1 : Lit le reseau LAN -> Transfere au port Python ephemere
 * - Thread 2 : Lit Python -> Broadcast au reseau LAN vers tous les peers connus
 *
 * Compilation Windows : gcc -o proxy_udp proxy_udp.c -lws2_32
 * Compilation Linux   : gcc -o proxy_udp proxy_udp.c -pthread
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
#define MAX_PEERS 8

typedef struct {
    struct sockaddr_in addr;
    int active;
} Peer;

static sock_t lan_sock = SOCK_INVALID;
static sock_t py_sock = SOCK_INVALID;

static struct sockaddr_in py_client_addr;
static int py_client_known = 0;

static Peer peers[MAX_PEERS];
static int peer_count = 0;

static void init_sockets(void) {
#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
#endif
}

static int same_peer_addr(const struct sockaddr_in *lhs, const struct sockaddr_in *rhs) {
    if (lhs == NULL || rhs == NULL) {
        return 0;
    }
    return lhs->sin_family == rhs->sin_family
        && lhs->sin_port == rhs->sin_port
        && lhs->sin_addr.s_addr == rhs->sin_addr.s_addr;
}

static int add_peer(struct sockaddr_in *addr) {
    int i;
    if (addr == NULL) {
        return -1;
    }
    for (i = 0; i < peer_count; i++) {
        if (peers[i].active && same_peer_addr(&peers[i].addr, addr)) {
            return i;
        }
    }
    if (peer_count >= MAX_PEERS) {
        printf("[LAN] Liste de peers pleine, peer ignore : %s:%d\n",
               inet_ntoa(addr->sin_addr), ntohs(addr->sin_port));
        return -1;
    }
    peers[peer_count].addr = *addr;
    peers[peer_count].active = 1;
    printf("-> [LAN] Nouveau peer ajoute : %s:%d (total=%d/%d)\n",
           inet_ntoa(addr->sin_addr),
           ntohs(addr->sin_port),
           peer_count + 1,
           MAX_PEERS);
    peer_count++;
    return peer_count - 1;
}

static void broadcast_to_peers(char *buffer, int len) {
    int i;
    if (buffer == NULL || len <= 0) {
        return;
    }
    for (i = 0; i < peer_count; i++) {
        if (!peers[i].active) {
            continue;
        }
        sendto(lan_sock, buffer, len, 0,
               (struct sockaddr*)&peers[i].addr,
               sizeof(peers[i].addr));
    }
}

static THREAD_RET lan_to_py_thread(void *arg) {
    char buffer[BUFFER_SIZE];
    struct sockaddr_in sender_addr;
    socklen_t sender_len;

    (void)arg;
    printf("[LAN] Thread d'ecoute reseau lance.\n");

    while (1) {
        sender_len = sizeof(sender_addr);
        int n = recvfrom(lan_sock, buffer, BUFFER_SIZE, 0, (struct sockaddr*)&sender_addr, &sender_len);
        if (n > 0) {
            add_peer(&sender_addr);
            if (py_client_known) {
                sendto(py_sock, buffer, n, 0, (struct sockaddr*)&py_client_addr, sizeof(py_client_addr));
            }
        }
    }
    THREAD_RETURN;
}

static THREAD_RET py_to_lan_thread(void *arg) {
    char buffer[BUFFER_SIZE];
    struct sockaddr_in sender_addr;
    socklen_t sender_len;

    (void)arg;
    printf("[IPC] Thread d'ecoute Python lance.\n");

    while (1) {
        sender_len = sizeof(sender_addr);
        int n = recvfrom(py_sock, buffer, BUFFER_SIZE, 0, (struct sockaddr*)&sender_addr, &sender_len);
        if (n > 0) {
            if (!py_client_known) {
                py_client_addr = sender_addr;
                py_client_known = 1;
                printf("-> [IPC] Client Python attache sur le port %d\n", ntohs(sender_addr.sin_port));
            }

            /* Management command from Python: ADD_PEER:ip:port */
            if (n > 9 && memcmp(buffer, "ADD_PEER:", 9) == 0) {
                char cmd_buf[256];
                int cmd_len = (n < 255) ? n : 255;
                memcpy(cmd_buf, buffer, cmd_len);
                cmd_buf[cmd_len] = '\0';

                char *ip_str = cmd_buf + 9;
                char *port_str = strchr(ip_str, ':');
                if (port_str) {
                    *port_str = '\0';
                    port_str++;
                    struct sockaddr_in new_peer;
                    memset(&new_peer, 0, sizeof(new_peer));
                    new_peer.sin_family = AF_INET;
                    new_peer.sin_port = htons(atoi(port_str));
                    inet_pton(AF_INET, ip_str, &new_peer.sin_addr);
                    add_peer(&new_peer);
                    printf("[LAN] Added peer via command: %s:%s\n", ip_str, port_str);
                }
                continue;
            }

            broadcast_to_peers(buffer, n);
        }
    }
    THREAD_RETURN;
}

int main(int argc, char *argv[]) {
    char *remote_ip = NULL;
    int py_port = 5000;
    int lan_listen_port = 6000;
    int remote_dest_port = 6000;
    int opt = 1;
    struct sockaddr_in lan_bind;
    struct sockaddr_in py_bind;

    printf("========== PROXY C (MODE UDP MULTI-PEERS + THREADS) ==========\n\n");

    if (argc >= 2 && strcmp(argv[1], "server") != 0) {
        remote_ip = argv[1];
    }
    if (argc >= 3) py_port = atoi(argv[2]);
    if (argc >= 4) lan_listen_port = atoi(argv[3]);
    if (argc >= 5) remote_dest_port = atoi(argv[4]);
    else remote_dest_port = lan_listen_port;

    init_sockets();

    lan_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    py_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);

    if (lan_sock == SOCK_INVALID || py_sock == SOCK_INVALID) {
        printf("[!] Erreur de creation des sockets UDP.\n");
        return 1;
    }

    setsockopt(lan_sock, SOL_SOCKET, SO_REUSEADDR, (char*)&opt, sizeof(opt));
    setsockopt(py_sock, SOL_SOCKET, SO_REUSEADDR, (char*)&opt, sizeof(opt));

    memset(&lan_bind, 0, sizeof(lan_bind));
    lan_bind.sin_family = AF_INET;
    lan_bind.sin_port = htons(lan_listen_port);
    lan_bind.sin_addr.s_addr = INADDR_ANY;
    if (bind(lan_sock, (struct sockaddr*)&lan_bind, sizeof(lan_bind)) < 0) {
        printf("[!] Erreur: Impossible de lier le socket LAN (port %d).\n", lan_listen_port);
        return 1;
    }

    memset(&py_bind, 0, sizeof(py_bind));
    py_bind.sin_family = AF_INET;
    py_bind.sin_port = htons(py_port);
    py_bind.sin_addr.s_addr = inet_addr("127.0.0.1");
    if (bind(py_sock, (struct sockaddr*)&py_bind, sizeof(py_bind)) < 0) {
        printf("[!] Erreur: Impossible de lier le socket Python (port %d).\n", py_port);
        return 1;
    }

    if (remote_ip != NULL) {
        struct sockaddr_in remote_peer_addr;
        memset(&remote_peer_addr, 0, sizeof(remote_peer_addr));
        remote_peer_addr.sin_family = AF_INET;
        remote_peer_addr.sin_port = htons(remote_dest_port);
        inet_pton(AF_INET, remote_ip, &remote_peer_addr.sin_addr);
        add_peer(&remote_peer_addr);
        printf("[LAN] Client UDP : peer initial %s:%d (ecoute sur %d)\n",
               remote_ip, remote_dest_port, lan_listen_port);
    } else {
        printf("[LAN] Serveur UDP : en attente de peers sur le port %d...\n", lan_listen_port);
    }

    printf("[IPC] En attente des paquets UDP de Python sur 127.0.0.1:%d...\n", py_port);

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
