"""
Pushover Notification Service
Sends push notifications via Pushover API
"""

import logging
import requests

logger = logging.getLogger(__name__)


class PushoverNotifier:
    """Send notifications via Pushover"""
    
    API_URL = "https://api.pushover.net/1/messages.json"
    
    def __init__(self, config):
        """
        Initialize Pushover notifier
        
        Args:
            config: ConfigManager instance
        """
        self.user_key = config.get("pushover", "user_key")
        self.api_token = config.get("pushover", "api_token")
        
        if not self.user_key or not self.api_token:
            logger.warning("Pushover credentials not configured")
    
    def send_notification(self, title: str, message: str, priority: int = 0, url: str = None) -> bool:
        """
        Send notification via Pushover
        
        Args:
            title: Notification title
            message: Notification message
            priority: Priority level (-2 to 2)
                -2: No notification/alert
                -1: Quiet notification
                0: Normal priority (default)
                1: High priority
                2: Emergency (requires acknowledgment)
            url: Optional URL to include in notification
            
        Returns:
            True if successful, False otherwise
        """
        if not self.user_key or not self.api_token:
            logger.error("Pushover not configured - notification not sent")
            return False
        
        try:
            payload = {
                "token": self.api_token,
                "user": self.user_key,
                "title": title,
                "message": message,
                "priority": priority
            }
            
            if url:
                payload["url"] = url
                payload["url_title"] = "View in KSeF"
            
            response = requests.post(self.API_URL, data=payload, timeout=10)
            response.raise_for_status()
            
            logger.info(f"Notification sent: {title}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send notification: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending notification: {e}")
            return False
    
    def send_error_notification(self, error_message: str) -> bool:
        """
        Send error notification with high priority
        
        Args:
            error_message: Error message to send
            
        Returns:
            True if successful, False otherwise
        """
        return self.send_notification(
            title="KSeF Monitor Error",
            message=error_message[:1024],  # Pushover max message length
            priority=1  # High priority for errors
        )
    
    def test_connection(self) -> bool:
        """
        Test Pushover connection by sending a test notification
        
        Returns:
            True if test successful
        """
        return self.send_notification(
            title="KSeF Monitor Test",
            message="Test notification - KSeF monitor is configured correctly!",
            priority=0
        )
