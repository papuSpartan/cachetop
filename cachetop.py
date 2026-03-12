#!/usr/bin/env python3
"""
cachetop - Real-time LVM cache monitoring tool similar to htop
Shows cache usage, hit ratio, and dirty blocks over time

Version: 2025.07
Author: Jerico Thomas
License: MIT
"""

import subprocess
import time
import os
import sys
from collections import deque
import re
import shutil
import termios
import tty

class LVMCacheMonitor:
    def __init__(self, vg_name="vg_games", lv_name="games", max_history=60):
        self.vg_name = vg_name
        self.lv_name = lv_name
        self.max_history = max_history
        
        # Data storage for graphs
        self.cache_usage_history = deque(maxlen=max_history)
        self.hit_ratio_history = deque(maxlen=max_history)
        self.dirty_ratio_history = deque(maxlen=max_history)
        self.read_hit_ratio_history = deque(maxlen=max_history)
        self.write_hit_ratio_history = deque(maxlen=max_history)
        
        # Terminal colors
        self.colors = {
            'reset': '\033[0m',
            'green': '\033[92m',
            'yellow': '\033[93m',
            'red': '\033[91m',
            'blue': '\033[94m',
            'cyan': '\033[96m',
            'bold': '\033[1m',
            'dim': '\033[2m'
        }
        
        # Cache terminal size
        self.terminal_width = 80
        self.terminal_height = 24
        self.update_terminal_size()
    
    def update_terminal_size(self):
        """Update cached terminal dimensions"""
        try:
            size = shutil.get_terminal_size()
            self.terminal_width = size.columns
            self.terminal_height = size.lines
        except (AttributeError, OSError):
            # Fallback to environment variables or defaults
            try:
                self.terminal_width = int(os.environ.get('COLUMNS', 80))
                self.terminal_height = int(os.environ.get('LINES', 24))
            except (ValueError, TypeError):
                self.terminal_width = 80
                self.terminal_height = 24
    
    def get_dynamic_widths(self):
        """Calculate dynamic widths based on terminal size"""
        # Update terminal size each time
        self.update_terminal_size()
        
        # Calculate bar width (leave space for labels and percentages)
        # Format: "Cache Usage   [BAR] 45.2%"
        label_space = 20  # Space for labels like "Cache Usage   ["
        percentage_space = 8  # Space for "] 45.2%"
        margin = 4  # Extra margin for safety
        
        bar_width = max(20, self.terminal_width - label_space - percentage_space - margin)
        
        # Calculate graph width for line charts
        # Format: "100%|GRAPH|"
        graph_label_space = 8  # Space for "100%|" and "|"
        graph_margin = 4
        
        graph_width = max(30, self.terminal_width - graph_label_space - graph_margin)
        
        return {
            'bar_width': bar_width,  # Remove cap, use full calculated width
            'graph_width': graph_width,  # Remove cap, use full calculated width
            'terminal_width': self.terminal_width
        }
    
    def get_lvm_cache_stats(self):
        """Get LVM cache statistics"""
        try:
            # Get cache pool information first
            pool_cmd = [
                'sudo', 'lvs', '--noheadings', '--nosuffix', '--units', 'b',
                '-o', 'lv_size',
                f'{self.vg_name}/{self.lv_name}'
            ]
            
            pool_result = subprocess.run(pool_cmd, capture_output=True, text=True, check=True)
            pool_size_bytes = int(pool_result.stdout.strip())
            
            # Get cache statistics
            cmd = [
                'sudo', 'lvs', '--noheadings', '--nosuffix', '--units', 'b',
                '-o', 'cache_total_blocks,cache_used_blocks,cache_dirty_blocks,cache_read_hits,cache_read_misses,cache_write_hits,cache_write_misses',
                f'{self.vg_name}/{self.lv_name}'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = result.stdout.strip()
            
            if not output:
                return None
                
            # Parse the output
            values = output.split()
            if len(values) >= 7:
                total_blocks = int(values[0])
                used_blocks = int(values[1])
                dirty_blocks = int(values[2])
                read_hits = int(values[3])
                read_misses = int(values[4])
                write_hits = int(values[5])
                write_misses = int(values[6])
                
                # Calculate cache block size from pool size and total blocks
                block_size = pool_size_bytes // total_blocks if total_blocks > 0 else 4096
                
                # Calculate percentages and ratios
                cache_usage_pct = (used_blocks / total_blocks * 100) if total_blocks > 0 else 0
                dirty_ratio_pct = (dirty_blocks / total_blocks * 100) if total_blocks > 0 else 0
                
                total_reads = read_hits + read_misses
                total_writes = write_hits + write_misses
                total_ops = total_reads + total_writes
                
                hit_ratio_pct = ((read_hits + write_hits) / total_ops * 100) if total_ops > 0 else 0
                read_hit_ratio_pct = (read_hits / total_reads * 100) if total_reads > 0 else 0
                write_hit_ratio_pct = (write_hits / total_writes * 100) if total_writes > 0 else 0
                
                # Estimate read vs write cache block distribution
                # This is an approximation based on operation ratios
                if total_ops > 0:
                    read_weight = total_reads / total_ops
                    write_weight = total_writes / total_ops
                else:
                    read_weight = 0.5
                    write_weight = 0.5
                
                # Estimate cache blocks used for reads vs writes
                estimated_read_blocks = int(used_blocks * read_weight)
                estimated_write_blocks = used_blocks - estimated_read_blocks
                
                return {
                    'total_blocks': total_blocks,
                    'used_blocks': used_blocks,
                    'dirty_blocks': dirty_blocks,
                    'cache_usage_pct': cache_usage_pct,
                    'dirty_ratio_pct': dirty_ratio_pct,
                    'hit_ratio_pct': hit_ratio_pct,
                    'read_hit_ratio_pct': read_hit_ratio_pct,
                    'write_hit_ratio_pct': write_hit_ratio_pct,
                    'read_hits': read_hits,
                    'read_misses': read_misses,
                    'write_hits': write_hits,
                    'write_misses': write_misses,
                    'total_reads': total_reads,
                    'total_writes': total_writes,
                    'total_ops': total_ops,
                    'block_size': block_size,
                    'pool_size_bytes': pool_size_bytes,
                    'estimated_read_blocks': estimated_read_blocks,
                    'estimated_write_blocks': estimated_write_blocks
                }
        except (subprocess.CalledProcessError, ValueError, IndexError) as e:
            return None
    
    def create_bar_graph(self, value, max_value=100, width=None, color='green'):
        """Create a horizontal bar graph"""
        if width is None:
            width = self.get_dynamic_widths()['bar_width']
            
        if max_value == 0:
            filled = 0
        else:
            filled = int((value / max_value) * width)
        
        bar = '█' * filled + '░' * (width - filled)
        color_code = self.colors.get(color, '')
        reset = self.colors['reset']
        
        return f"{color_code}{bar}{reset}"
    
    def create_dual_cache_bar(self, read_blocks, write_blocks, total_blocks, width=None):
        """Create a dual-color cache usage bar showing read vs write blocks"""
        if width is None:
            width = self.get_dynamic_widths()['bar_width']
            
        if total_blocks == 0:
            return '░' * width
        
        # Calculate proportions
        read_portion = int((read_blocks / total_blocks) * width)
        write_portion = int((write_blocks / total_blocks) * width)
        
        # Ensure we don't exceed width due to rounding
        used_portion = read_portion + write_portion
        if used_portion > width:
            if read_portion >= write_portion:
                read_portion = width - write_portion
            else:
                write_portion = width - read_portion
            used_portion = read_portion + write_portion
        
        empty_portion = width - used_portion
        
        # Create the bar with colors
        green = self.colors['green']
        red = self.colors['red']
        reset = self.colors['reset']
        
        read_bar = f"{green}{'█' * read_portion}{reset}"
        write_bar = f"{red}{'█' * write_portion}{reset}"
        empty_bar = '░' * empty_portion
        
        return read_bar + write_bar + empty_bar
    
    def create_line_graph(self, data, width=None, height=8):
        """Create a simple ASCII line graph"""
        if width is None:
            width = self.get_dynamic_widths()['graph_width']
            
        if not data or len(data) < 2:
            return [''] * height
        
        # Normalize data to fit in height
        min_val = min(data)
        max_val = max(data)
        range_val = max_val - min_val if max_val != min_val else 1
        
        lines = [' ' * width for _ in range(height)]
        
        for i, value in enumerate(data[-width:]):
            x = i
            if x >= width:
                break
            
            # Convert value to y position (inverted because we draw top to bottom)
            y = height - 1 - int(((value - min_val) / range_val) * (height - 1))
            y = max(0, min(height - 1, y))
            
            # Replace character at position
            line_list = list(lines[y])
            line_list[x] = '●'
            lines[y] = ''.join(line_list)
        
        return lines
    
    def clear_screen(self):
        """Clear the terminal screen"""
        os.system('clear')
    
    def format_size(self, blocks, block_size=None):
        """Format block count to human readable size"""
        if block_size is None:
            block_size = 4096  # Default block size
        bytes_size = blocks * block_size
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f}{unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f}PB"
    
    def format_bytes(self, bytes_size):
        """Format bytes to human readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f}{unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f}PB"
    
    def display_stats(self, stats):
        """Display current statistics and graphs"""
        if not stats:
            print(f"{self.colors['red']}Error: Could not retrieve LVM cache statistics{self.colors['reset']}")
            print("Make sure the volume group and logical volume exist and you have sudo privileges.")
            return
        
        self.clear_screen()
        
        # Get dynamic widths for this refresh
        widths = self.get_dynamic_widths()
        
        # Header - adjust based on terminal width
        header_text = f"cachetop - {self.vg_name}/{self.lv_name}"
        separator = "=" * min(len(header_text) + 10, widths['terminal_width'])
        
        print(f"{self.colors['bold']}{self.colors['cyan']}{header_text}{self.colors['reset']}")
        print(separator)
        print()
        
        # Current stats
        print(f"{self.colors['bold']}Current Statistics:{self.colors['reset']}")
        
        # Show actual cache pool size
        cache_pool_size = self.format_bytes(stats['pool_size_bytes'])
        used_cache_size = self.format_size(stats['used_blocks'], stats['block_size'])
        dirty_cache_size = self.format_size(stats['dirty_blocks'], stats['block_size'])
        read_cache_size = self.format_size(stats['estimated_read_blocks'], stats['block_size'])
        write_cache_size = self.format_size(stats['estimated_write_blocks'], stats['block_size'])
        
        print(f"Cache Pool:   {cache_pool_size} total")
        print(f"Cache Usage:  {stats['cache_usage_pct']:.1f}% ({used_cache_size} used)")
        print(f"  ├─ Reads:   ~{read_cache_size} ({stats['estimated_read_blocks']} blocks)")
        print(f"  └─ Writes:  ~{write_cache_size} ({stats['estimated_write_blocks']} blocks)")
        print(f"Dirty Blocks: {stats['dirty_ratio_pct']:.1f}% ({dirty_cache_size} dirty)")
        print(f"Hit Ratio:    {stats['hit_ratio_pct']:.1f}% ({stats['total_ops']} total operations)")
        print(f"Read Hits:    {stats['read_hit_ratio_pct']:.1f}% ({stats['total_reads']} read operations)")
        print(f"Write Hits:   {stats['write_hit_ratio_pct']:.1f}% ({stats['total_writes']} write operations)")
        print()
        
        # Bar graphs
        print(f"{self.colors['bold']}Real-time Status:{self.colors['reset']}")
        
        # Dual-color cache usage bar (read vs write)
        dual_cache_bar = self.create_dual_cache_bar(
            stats['estimated_read_blocks'], 
            stats['estimated_write_blocks'], 
            stats['total_blocks']
        )
        print(f"Cache Usage   [{dual_cache_bar}] {stats['cache_usage_pct']:.1f}%")
        print(f"              {self.colors['green']}█{self.colors['reset']} Read cache  {self.colors['red']}█{self.colors['reset']} Write cache  ░ Free")
        
        # Dirty blocks bar
        dirty_color = 'blue'  # Changed to blue color
        dirty_bar = self.create_bar_graph(stats['dirty_ratio_pct'], 100, None, dirty_color)
        print(f"Dirty Blocks  [{dirty_bar}] {stats['dirty_ratio_pct']:.1f}%")
        
        # Hit ratio bar
        hit_color = 'green' if stats['hit_ratio_pct'] > 80 else 'yellow' if stats['hit_ratio_pct'] > 60 else 'red'
        hit_bar = self.create_bar_graph(stats['hit_ratio_pct'], 100, None, hit_color)
        print(f"Hit Ratio     [{hit_bar}] {stats['hit_ratio_pct']:.1f}%")
        
        # Read hit ratio bar
        read_hit_color = 'green' if stats['read_hit_ratio_pct'] > 80 else 'yellow' if stats['read_hit_ratio_pct'] > 60 else 'red'
        read_hit_bar = self.create_bar_graph(stats['read_hit_ratio_pct'], 100, None, read_hit_color)
        print(f"Read Hits     [{read_hit_bar}] {stats['read_hit_ratio_pct']:.1f}%")
        
        # Write hit ratio bar
        write_hit_color = 'green' if stats['write_hit_ratio_pct'] > 80 else 'yellow' if stats['write_hit_ratio_pct'] > 60 else 'red'
        write_hit_bar = self.create_bar_graph(stats['write_hit_ratio_pct'], 100, None, write_hit_color)
        print(f"Write Hits    [{write_hit_bar}] {stats['write_hit_ratio_pct']:.1f}%")
        print()
        
        # Historical line graphs
        if len(self.cache_usage_history) > 1:
            print(f"{self.colors['bold']}Historical Trends (last {len(self.cache_usage_history)} samples):{self.colors['reset']}")
            print()
            
            # Cache usage graph
            print(f"{self.colors['green']}Cache Usage Over Time:{self.colors['reset']}")
            usage_lines = self.create_line_graph(list(self.cache_usage_history))
            graph_width = len(usage_lines[0]) if usage_lines else widths['graph_width']
            for i, line in enumerate(usage_lines):
                print(f"{100 - (i * 100 // len(usage_lines)):3d}%|{line}|")
            print("    " + "-" * graph_width)
            print(f"    {len(self.cache_usage_history)} samples ago{' ' * (graph_width - 15)}now")
            print()
            
            # Hit ratio graph
            print(f"{self.colors['blue']}Hit Ratio Over Time:{self.colors['reset']}")
            hit_lines = self.create_line_graph(list(self.hit_ratio_history))
            for i, line in enumerate(hit_lines):
                print(f"{100 - (i * 100 // len(hit_lines)):3d}%|{line}|")
            print("    " + "-" * graph_width)
            print(f"    {len(self.hit_ratio_history)} samples ago{' ' * (graph_width - 15)}now")
            print()
            
            # Read hit ratio graph
            print(f"{self.colors['cyan']}Read Hit Ratio Over Time:{self.colors['reset']}")
            read_hit_lines = self.create_line_graph(list(self.read_hit_ratio_history))
            for i, line in enumerate(read_hit_lines):
                print(f"{100 - (i * 100 // len(read_hit_lines)):3d}%|{line}|")
            print("    " + "-" * graph_width)
            print(f"    {len(self.read_hit_ratio_history)} samples ago{' ' * (graph_width - 15)}now")
            print()
            
            # Write hit ratio graph
            print(f"{self.colors['yellow']}Write Hit Ratio Over Time:{self.colors['reset']}")
            write_hit_lines = self.create_line_graph(list(self.write_hit_ratio_history))
            for i, line in enumerate(write_hit_lines):
                print(f"{100 - (i * 100 // len(write_hit_lines)):3d}%|{line}|")
            print("    " + "-" * graph_width)
            print(f"    {len(self.write_hit_ratio_history)} samples ago{' ' * (graph_width - 15)}now")
        
        # Add terminal size info at bottom
        print()
        print(f"{self.colors['dim']}Terminal: {widths['terminal_width']}x{self.terminal_height} | Bar width: {widths['bar_width']} | Graph width: {widths['graph_width']} | Press Ctrl+C to exit{self.colors['reset']}")
    
    def run(self, refresh_interval=2):
        """Main monitoring loop"""
        print(f"{self.colors['cyan']}Starting cachetop...{self.colors['reset']}")
        print(f"Monitoring: {self.vg_name}/{self.lv_name}")
        print(f"Refresh interval: {refresh_interval} seconds")
        time.sleep(2)
        
        try:
            while True:
                stats = self.get_lvm_cache_stats()
                
                if stats:
                    # Store historical data
                    self.cache_usage_history.append(stats['cache_usage_pct'])
                    self.hit_ratio_history.append(stats['hit_ratio_pct'])
                    self.dirty_ratio_history.append(stats['dirty_ratio_pct'])
                    self.read_hit_ratio_history.append(stats['read_hit_ratio_pct'])
                    self.write_hit_ratio_history.append(stats['write_hit_ratio_pct'])
                
                self.display_stats(stats)
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            print(f"\n{self.colors['cyan']}Monitoring stopped.{self.colors['reset']}")
            sys.exit(0)

def detect_cache_volumes():
    """Detect available LVM cache volumes"""
    try:
        # Find all logical volumes with cache
        cmd = ['sudo', 'lvs', '--noheadings', '--nosuffix', '-o', 'vg_name,lv_name,cache_policy', '--separator', '|']
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        cache_volumes = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3 and parts[2] and parts[2] != '':  # Has cache policy
                    vg_name = parts[0]
                    lv_name = parts[1]
                    cache_volumes.append((vg_name, lv_name))
        
        return cache_volumes
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

def get_key():
    """Get a single keypress from stdin"""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        # Handle arrow keys
        if ch == '\x1b':  # ESC sequence
            ch += sys.stdin.read(2)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def interactive_volume_selection(cache_volumes):
    """Interactive menu to select cache volume"""
    if not cache_volumes:
        print("No LVM cache volumes detected.")
        return None, None
    
    print("\n" + "=" * 60)
    print("cachetop - LVM Cache Volume Selection")
    print("=" * 60)
    print("Use ↑/↓ arrow keys to navigate, Enter to select, Ctrl+C to exit\n")
    
    selected = 0
    
    while True:
        # Clear previous menu (move cursor up and clear lines)
        if selected > 0 or True:  # Always clear on first display too
            print(f"\033[{len(cache_volumes) + 2}A", end="")  # Move cursor up
            print("\033[J", end="")  # Clear from cursor to end of screen
        
        # Display menu
        for i, (vg, lv) in enumerate(cache_volumes):
            if i == selected:
                print(f"  → \033[92m{vg}/{lv}\033[0m")  # Green highlight
            else:
                print(f"    {vg}/{lv}")
        
        print(f"\nSelected: \033[93m{cache_volumes[selected][0]}/{cache_volumes[selected][1]}\033[0m")
        
        # Get user input
        try:
            key = get_key()
            
            if key == '\x1b[A':  # Up arrow
                selected = (selected - 1) % len(cache_volumes)
            elif key == '\x1b[B':  # Down arrow
                selected = (selected + 1) % len(cache_volumes)
            elif key == '\r' or key == '\n':  # Enter
                vg_name, lv_name = cache_volumes[selected]
                print(f"\n\033[96mSelected: {vg_name}/{lv_name}\033[0m")
                print("Starting monitor...\n")
                return vg_name, lv_name
            elif key == '\x03':  # Ctrl+C
                print("\n\033[91mSelection cancelled.\033[0m")
                sys.exit(0)
                
        except KeyboardInterrupt:
            print("\n\033[91mSelection cancelled.\033[0m")
            sys.exit(0)
    
    def run(self, refresh_interval=2):
        """Main monitoring loop"""
        print(f"{self.colors['cyan']}Starting LVM Cache Monitor...{self.colors['reset']}")
        print(f"Monitoring: {self.vg_name}/{self.lv_name}")
        print(f"Refresh interval: {refresh_interval} seconds")
        time.sleep(2)
        
        try:
            while True:
                stats = self.get_lvm_cache_stats()
                
                if stats:
                    # Store historical data
                    self.cache_usage_history.append(stats['cache_usage_pct'])
                    self.hit_ratio_history.append(stats['hit_ratio_pct'])
                    self.dirty_ratio_history.append(stats['dirty_ratio_pct'])
                    self.read_hit_ratio_history.append(stats['read_hit_ratio_pct'])
                    self.write_hit_ratio_history.append(stats['write_hit_ratio_pct'])
                
                self.display_stats(stats)
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            print(f"\n{self.colors['cyan']}Monitoring stopped.{self.colors['reset']}")
            sys.exit(0)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='cachetop - Real-time LVM cache monitor')
    parser.add_argument('--version', action='version', version='cachetop 2025.07')
    parser.add_argument('--vg', help='Volume group name')
    parser.add_argument('--lv', help='Logical volume name')
    parser.add_argument('--interval', type=int, default=2, help='Refresh interval in seconds (default: 2)')
    parser.add_argument('--history', type=int, default=60, help='Number of historical samples to keep (default: 60)')
    parser.add_argument('--pick', action='store_true', help='Force interactive volume selection even if auto-detection works')
    
    args = parser.parse_args()
    
    vg_name = args.vg
    lv_name = args.lv
    
    # If both VG and LV are provided, use them directly
    if vg_name and lv_name and not args.pick:
        print(f"\033[96mUsing specified volume: {vg_name}/{lv_name}\033[0m")
    else:
        # Auto-detect cache volumes
        print("\033[96mDetecting LVM cache volumes...\033[0m")
        cache_volumes = detect_cache_volumes()
        
        if not cache_volumes:
            print("\033[91mNo LVM cache volumes found.\033[0m")
            print("Make sure you have LVM cache configured and proper sudo privileges.")
            sys.exit(1)
        elif len(cache_volumes) == 1 and not args.pick:
            # Only one cache volume found, use it automatically
            vg_name, lv_name = cache_volumes[0]
            print(f"\033[92mAuto-detected cache volume: {vg_name}/{lv_name}\033[0m")
        else:
            # Multiple volumes or --pick flag, show selection menu
            if args.pick:
                print("Interactive selection requested with --pick flag")
            else:
                print(f"Found {len(cache_volumes)} cache volumes")
            vg_name, lv_name = interactive_volume_selection(cache_volumes)
            
            if not vg_name or not lv_name:
                print("\033[91mNo volume selected.\033[0m")
                sys.exit(1)
    
    # Verify the selected volume has cache
    try:
        test_cmd = ['sudo', 'lvs', '--noheadings', '-o', 'cache_policy', f'{vg_name}/{lv_name}']
        result = subprocess.run(test_cmd, capture_output=True, text=True, check=True)
        if not result.stdout.strip():
            print(f"\033[91mError: {vg_name}/{lv_name} does not appear to have cache configured.\033[0m")
            sys.exit(1)
    except subprocess.CalledProcessError:
        print(f"\033[91mError: Cannot access {vg_name}/{lv_name}. Check volume names and permissions.\033[0m")
        sys.exit(1)
    
    monitor = LVMCacheMonitor(vg_name, lv_name, args.history)
    monitor.run(args.interval)

if __name__ == "__main__":
    main()
