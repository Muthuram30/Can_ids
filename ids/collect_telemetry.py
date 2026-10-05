"""
Telemetry Collection for CAN IDS

Collects system telemetry for training and monitoring.
Gathers data from CAN, network, USB, and system resources.
"""

import json
import os
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
import psutil


@dataclass
class SystemTelemetry:
    """System resource telemetry."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_available_mb: float
    process_count: int
    socket_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NetworkTelemetry:
    """Network connection telemetry."""
    timestamp: float
    connection_count: int
    established_count: int
    listen_count: int
    source_ips: List[str]
    source_macs: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CANTelemetry:
    """CAN bus telemetry."""
    timestamp: float
    frame_count: int
    message_rate: float
    unique_ids: List[int]
    unknown_ids: List[int]
    error_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TelemetryCollector:
    """
    Collects and stores system telemetry for IDS training/monitoring.
    """
    
    def __init__(self, buffer_size: int = 1000, output_dir: str = "data"):
        """
        Initialize telemetry collector.
        
        Args:
            buffer_size: Maximum samples to keep in memory
            output_dir: Directory to save telemetry logs
        """
        self.buffer_size = buffer_size
        self.output_dir = output_dir
        
        self.system_buffer = deque(maxlen=buffer_size)
        self.network_buffer = deque(maxlen=buffer_size)
        self.can_buffer = deque(maxlen=buffer_size)
        
        os.makedirs(output_dir, exist_ok=True)
    
    def collect_system_telemetry(self) -> SystemTelemetry:
        """Collect current system resource telemetry."""
        
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        # Count processes and sockets
        try:
            process_count = len(list(psutil.process_iter()))
        except:
            process_count = 0
        
        try:
            socket_count = len(psutil.net_connections())
        except:
            socket_count = 0
        
        telemetry = SystemTelemetry(
            timestamp=time.time(),
            cpu_percent=cpu,
            memory_percent=memory.percent,
            memory_available_mb=memory.available / (1024 * 1024),
            process_count=process_count,
            socket_count=socket_count
        )
        
        self.system_buffer.append(telemetry)
        return telemetry
    
    def collect_network_telemetry(self) -> Optional[NetworkTelemetry]:
        """Collect network connection telemetry."""
        
        try:
            connections = psutil.net_connections(kind='inet')
            
            established = [c for c in connections if c.status == 'ESTABLISHED']
            listen = [c for c in connections if c.status == 'LISTEN']
            
            source_ips = list(set(
                c.raddr.ip for c in established 
                if c.raddr
            ))
            
            telemetry = NetworkTelemetry(
                timestamp=time.time(),
                connection_count=len(connections),
                established_count=len(established),
                listen_count=len(listen),
                source_ips=source_ips,
                source_macs=[]  # Would need additional tools to map IP→MAC
            )
            
            self.network_buffer.append(telemetry)
            return telemetry
            
        except (PermissionError, OSError):
            return None
    
    def record_can_window(
        self,
        frames: List[tuple],
        known_ids: set,
        errors: int = 0
    ) -> CANTelemetry:
        """
        Record telemetry for a CAN traffic window.
        
        Args:
            frames: List of (timestamp, arbitration_id, data) tuples
            known_ids: Set of expected/authorized CAN IDs
            errors: Number of errors encountered
        """
        if not frames:
            telemetry = CANTelemetry(
                timestamp=time.time(),
                frame_count=0,
                message_rate=0.0,
                unique_ids=[],
                unknown_ids=[],
                error_count=errors
            )
        else:
            timestamps = [f[0] for f in frames]
            ids_seen = set(f[1] for f in frames)
            unknown = [id for id in ids_seen if id not in known_ids]
            
            duration = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 1.0
            rate = len(frames) / duration if duration > 0 else 0.0
            
            telemetry = CANTelemetry(
                timestamp=time.time(),
                frame_count=len(frames),
                message_rate=rate,
                unique_ids=sorted(ids_seen),
                unknown_ids=sorted(unknown),
                error_count=errors
            )
        
        self.can_buffer.append(telemetry)
        return telemetry
    
    def save_to_file(self, filename: Optional[str] = None) -> str:
        """
        Save collected telemetry to JSON file.
        
        Args:
            filename: Optional filename (auto-generated if None)
            
        Returns:
            Path to saved file
        """
        if filename is None:
            filename = f"telemetry_{time.strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = os.path.join(self.output_dir, filename)
        
        data = {
            'collected_at': time.time(),
            'system': [t.to_dict() for t in self.system_buffer],
            'network': [t.to_dict() for t in self.network_buffer],
            'can': [t.to_dict() for t in self.can_buffer],
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        return filepath
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of collected telemetry."""
        return {
            'system_samples': len(self.system_buffer),
            'network_samples': len(self.network_buffer),
            'can_samples': len(self.can_buffer),
            'buffer_size': self.buffer_size
        }
