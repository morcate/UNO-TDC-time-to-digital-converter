/*
 * Filename: synchronousSPI.cpp
 * Version: 2.0
 * Date: 2026-06-14
 * Author: Leonardo Lisa, Caterina Morgavi
 * Description: Bit-banging SPI function implementations.
 *
 */

#include "synchronousSPI.h"

void shiftOutLSB(uint8_t _data)
{
  for (uint8_t j = 1; j < 0b10000000; j <<= 1)
  {
    if ((_data & j) == 0)
    {
      PORTB &= ~DOUT;
    }
    else
    {
      PORTB |= DOUT;
    }

    PORTB |= SCLK;
    PORTB &= ~SCLK & ~DOUT;
  }

  if ((_data & 0b10000000) == 0)
  {
    PORTB &= ~DOUT;
  }
  else
  {
    PORTB |= DOUT;
  }
  PORTB |= SCLK;
  PORTB &= ~SCLK & ~DOUT;
}

void shiftOutMSB(uint8_t _data)
{
  for (uint8_t j = 0b10000000; j > 0b00000001; j >>= 1)
  {
    if ((_data & j) == 0)
    {
      PORTB &= ~DOUT;
    }
    else
    {
      PORTB |= DOUT;
    }

    PORTB |= SCLK;
    __asm__("nop\n\t");
    PORTB &= ~SCLK & ~DOUT;
  }

  if ((_data & 0b00000001) == 0)
  {
    PORTB &= ~DOUT;
  }
  else
  {
    PORTB |= DOUT;
  }
  PORTB |= SCLK;
  __asm__("nop\n\t");
  PORTB &= ~SCLK & ~DOUT;
}

uint8_t getByte(void)
{
  uint8_t _data = 0; // MSB first
  for (uint8_t i = 0x80; i > 0; i >>= 1)
  {
    PORTB |= SCLK; // Data on falling edge
    PORTB &= ~SCLK;
    if (!!(PINB & DIN))
    {
      _data |= i;
    }
  }
  return _data;
}