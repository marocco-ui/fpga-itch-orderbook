FILE(GLOB_RECURSE app_sources ${CMAKE_SOURCE_DIR}/src/*.*)
idf_component_register(SRCS ${app_sources})

# 4096 resting orders (about 98 KB) leaves room in RAM for WiFi later.
# Raise to 13 if the report shows ERR from a full order table.
target_compile_definitions(${COMPONENT_LIB} PRIVATE BOOK_ORDER_BITS=12)

# Built-in USB Serial/JTAG by default. For a USB-UART bridge board, add:
# target_compile_definitions(${COMPONENT_LIB} PRIVATE ITCH_USE_UART0=1)
