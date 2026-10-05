"""
Security Policy Engine for CAN IDS

Separates ML detection from security response actions.
The ML model NEVER directly executes system commands.

Detection Flow:
    ML Model → Policy Engine → Validated Action → Execution
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
import time


class ThreatLevel(Enum):
    """Threat severity levels."""
    NONE = 0
    SUSPECTED = 1
    CONFIRMED = 2
    CRITICAL = 3


class SecurityAction(Enum):
    """Available security actions."""
    ALLOW = "allow"
    MONITOR = "monitor"
    ALERT = "alert"
    ISOLATE = "isolate"
    SAFE_STATE = "safe_state"
    BLOCK = "block"


@dataclass
class PolicyDecision:
    """
    Result of policy evaluation.
    
    Contains both the decision and the reasoning for audit/logging.
    """
    action: SecurityAction
    threat_level: ThreatLevel
    reason: str
    source_ip: Optional[str] = None
    attack_type: Optional[str] = None
    confidence: Optional[float] = None
    should_log: bool = True
    should_alert: bool = False
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'action': self.action.value,
            'threat_level': self.threat_level.name,
            'reason': self.reason,
            'source_ip': self.source_ip,
            'attack_type': self.attack_type,
            'confidence': self.confidence,
            'should_log': self.should_log,
            'should_alert': self.should_alert,
            'metadata': self.metadata or {},
            'timestamp': time.time()
        }


class PolicyEngine:
    """
    Security policy engine for CAN IDS.
    
    Makes deterministic, rule-based decisions about how to respond to
    ML detection results. Configuration allows tuning sensitivity vs.
    false positive tolerance.
    """
    
    def __init__(
        self,
        isolation_enabled: bool = True,
        anomaly_threshold: float = 0.0,
        confidence_threshold: float = 0.7,
        safe_state_on_critical: bool = True
    ):
        """
        Initialize policy engine.
        
        Args:
            isolation_enabled: Whether isolation actions are enabled
            anomaly_threshold: Score threshold for anomaly detection (IF)
            confidence_threshold: Min confidence for supervised models (RF)
            safe_state_on_critical: Trigger safe state on critical threats
        """
        self.isolation_enabled = isolation_enabled
        self.anomaly_threshold = anomaly_threshold
        self.confidence_threshold = confidence_threshold
        self.safe_state_on_critical = safe_state_on_critical
        
        self.detection_history = []
        self.max_history = 100
    
    def evaluate(
        self,
        model_result,  # ModelResult from ids.models
        source_ip: Optional[str] = None,
        system_state: Optional[Dict[str, Any]] = None
    ) -> PolicyDecision:
        """
        Evaluate detection result and decide on security action.
        
        Args:
            model_result: ModelResult from ML model
            source_ip: Source IP if network-based detection
            system_state: Additional system context
            
        Returns:
            PolicyDecision with action and reasoning
        """
        system_state = system_state or {}
        
        # Record detection
        self.detection_history.append({
            'timestamp': time.time(),
            'model': model_result.model_name,
            'is_attack': model_result.is_attack,
            'source_ip': source_ip
        })
        if len(self.detection_history) > self.max_history:
            self.detection_history.pop(0)
        
        # NORMAL: No attack detected
        if not model_result.is_attack:
            return PolicyDecision(
                action=SecurityAction.ALLOW,
                threat_level=ThreatLevel.NONE,
                reason="No threat detected - normal traffic pattern",
                source_ip=source_ip,
                should_log=False
            )
        
        # ATTACK DETECTED: Evaluate severity and response
        
        # Isolation Forest (unsupervised)
        if model_result.model_name == "IsolationForest":
            score = model_result.anomaly_score
            
            # Severe anomaly (very negative score)
            if score < -0.2:
                return self._handle_critical_threat(
                    source_ip=source_ip,
                    reason=f"Critical CAN anomaly detected (score={score:.3f})",
                    attack_type="CAN_ANOMALY",
                    confidence=1.0 - min(1.0, abs(score))
                )
            
            # Moderate anomaly
            elif score < self.anomaly_threshold:
                return PolicyDecision(
                    action=SecurityAction.ALERT if self.isolation_enabled else SecurityAction.MONITOR,
                    threat_level=ThreatLevel.SUSPECTED,
                    reason=f"CAN anomaly suspected (score={score:.3f})",
                    source_ip=source_ip,
                    attack_type="CAN_ANOMALY",
                    confidence=abs(score) / 0.3,
                    should_alert=True
                )
        
        # Random Forest (supervised)
        elif model_result.model_name == "RandomForest":
            prediction = model_result.prediction
            confidence = model_result.confidence
            
            # High confidence attack detection
            if confidence >= self.confidence_threshold:
                # Critical attacks (CAN-level, direct vehicle control)
                if prediction in ["CAN_ATTACK", "CAN_FLOOD", "PAYLOAD_ANOMALY"]:
                    return self._handle_critical_threat(
                        source_ip=source_ip,
                        reason=f"Critical attack detected: {prediction} (confidence={confidence:.2%})",
                        attack_type=prediction,
                        confidence=confidence
                    )
                
                # Network/USB attacks (isolation at application layer)
                else:
                    return PolicyDecision(
                        action=SecurityAction.ISOLATE if self.isolation_enabled else SecurityAction.ALERT,
                        threat_level=ThreatLevel.CONFIRMED,
                        reason=f"Attack detected: {prediction} (confidence={confidence:.2%})",
                        source_ip=source_ip,
                        attack_type=prediction,
                        confidence=confidence,
                        should_alert=True
                    )
            
            # Low confidence - suspicious but not confirmed
            else:
                return PolicyDecision(
                    action=SecurityAction.MONITOR,
                    threat_level=ThreatLevel.SUSPECTED,
                    reason=f"Suspicious activity: {prediction} (confidence={confidence:.2%} below threshold)",
                    source_ip=source_ip,
                    attack_type=prediction,
                    confidence=confidence,
                    should_alert=False
                )
        
        # Default: Unknown model - conservative response
        return PolicyDecision(
            action=SecurityAction.MONITOR,
            threat_level=ThreatLevel.SUSPECTED,
            reason=f"Unknown model {model_result.model_name} flagged anomaly",
            source_ip=source_ip,
            should_alert=True
        )
    
    def _handle_critical_threat(
        self,
        source_ip: Optional[str],
        reason: str,
        attack_type: str,
        confidence: float
    ) -> PolicyDecision:
        """Handle critical threats that may require safe state."""
        
        if self.isolation_enabled and self.safe_state_on_critical:
            action = SecurityAction.SAFE_STATE
        elif self.isolation_enabled:
            action = SecurityAction.ISOLATE
        else:
            action = SecurityAction.ALERT
        
        return PolicyDecision(
            action=action,
            threat_level=ThreatLevel.CRITICAL,
            reason=reason,
            source_ip=source_ip,
            attack_type=attack_type,
            confidence=confidence,
            should_alert=True
        )
    
    def get_detection_summary(self) -> Dict[str, Any]:
        """Get summary of recent detections."""
        if not self.detection_history:
            return {'total': 0, 'attacks': 0, 'normal': 0}
        
        attacks = sum(1 for d in self.detection_history if d['is_attack'])
        
        return {
            'total': len(self.detection_history),
            'attacks': attacks,
            'normal': len(self.detection_history) - attacks,
            'attack_rate': attacks / len(self.detection_history),
            'recent_window': len(self.detection_history)
        }
    
    def update_configuration(self, **kwargs) -> None:
        """Update policy configuration at runtime."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
