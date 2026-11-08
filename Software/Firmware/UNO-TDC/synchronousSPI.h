/*
 * Filename: synchronousSPI.h
 * Version: 2.0
 * Date: 2026-06-14
 * Author: Leonardo Lisa, Caterina Morgavi
 * Description: Bit-banging SPI function declarations.
 *
 */

#ifndef SYNCHRONOUSSPI_H_
#define SYNCHRONOUSSPI_H_

#include <avr/io.h>
#include <stdint.h>

/* SPI Pin Mapping (PORTB) */
#define SCLK 0x02   // PB1 9 -> TDC7200 SCLK
#define DOUT 0x08   // PB3 11 -> TDC7200 DIN
#define DIN  0x10   // PB4 12 -> TDC7200 DOUT

void shiftOutMSB(uint8_t _data);
void shiftOutLSB(uint8_t _data);
uint8_t getByte(void);

#endif // SYNCHRONOUSSPI_H_