CC = gcc
CFLAGS = -Wall -Wextra -O2
LDFLAGS = -pthread

# Detect OS
ifeq ($(OS),Windows_NT)
    EXTENSION = .exe
    LDFLAGS += -lws2_32
else
    EXTENSION =
endif

TARGETS = network/proxy_udp_real_ip$(EXTENSION) network/proxy_udp$(EXTENSION) network/proxy$(EXTENSION)

all: $(TARGETS)

network/%$(EXTENSION): network/%.c
	$(CC) $(CFLAGS) $< -o $@ $(LDFLAGS)

clean:
	rm -f network/*.exe network/proxy_udp_real_ip network/proxy_udp network/proxy

.PHONY: all clean
