#include "stdio_eater.h"

int main(void) {
    int freq, dur;
    printf("Enter frequency (Hz): ");
    scanf("%d", &freq);
    printf("Enter duration (ms): ");
    scanf("%d", &dur);
    printf("Beeping at %d Hz for %d ms...\n", freq, dur);
    beep(freq, dur);
    printf("Done!\n");
    return 0;
}
