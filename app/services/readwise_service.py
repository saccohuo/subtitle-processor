"""Readwise integration service for saving content to Readwise Reader."""

import logging
import requests
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

try:
    from ..config.config_manager import get_config_value
except ImportError:
    from config.config_manager import get_config_value

logger = logging.getLogger(__name__)


class ReadwiseService:
    """Service for integrating with Readwise Reader API."""
    
    def __init__(self):
        self.api_token = get_config_value('tokens.readwise')
        self.api_base_url = 'https://readwise.io/api/v3'
        self.max_content_length = 1000000  # 1MB limit for content
        
        if not self.api_token:
            logger.warning("Readwise API token not configured")
    
    def is_configured(self) -> bool:
        """Check if Readwise service is properly configured."""
        return bool(self.api_token)
    
    def save_to_readwise(self, content: str, title: str, url: str, 
                        video_info: Optional[Dict[str, Any]] = None, 
                        published_date: Optional[str] = None,
                        author: Optional[str] = None,
                        location: str = 'new',
                        tags: Optional[List[str]] = None,
                        language: Optional[str] = None) -> bool:
        """
        Save content to Readwise Reader.
        
        Args:
            content: Text content to save
            title: Article title
            url: Source URL
            video_info: Optional video metadata
            published_date: Published date string
            author: Author name
            location: Save location ('new', 'later', 'archive', 'feed')
            tags: List of tags
            language: Content language
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_configured():
            logger.error("Readwise not configured, skipping save")
            return False
        
        try:
            logger.info(f"开始发送内容到Readwise: {title}")
            logger.info(f"Readwise URL: {url}")
            logger.info(f"内容长度: {len(content)} 字符")
            
            # Prepare article data
            article_data = self._prepare_article_data(content, title, url, video_info, 
                                                    published_date, author, location, tags, language)
            logger.info(f"准备的文章数据: 标题={article_data.get('title')}, URL={article_data.get('url')}, 位置={article_data.get('location')}")
            
            # Check content length and split if necessary
            if len(content) > self.max_content_length:
                logger.info("Content too long, splitting into multiple articles")
                return self._save_long_content(content, title, url, video_info, 
                                               published_date, author, location, tags, language)
            
            # Save single article
            return self._save_single_article(article_data)
            
        except Exception as e:
            logger.error(f"❌ 保存到Readwise时发生错误: {str(e)}")
            logger.exception("详细错误堆栈:")
            return False
    
    def _prepare_article_data(self, content: str, title: str, url: str, 
                            video_info: Optional[Dict[str, Any]] = None,
                            published_date: Optional[str] = None,
                            author: Optional[str] = None,
                            location: str = 'new',
                            tags: Optional[List[str]] = None,
                            language: Optional[str] = None) -> Dict[str, Any]:
        """Prepare article data for Readwise API."""
        
        # Format content with metadata
        formatted_content = self._format_content_with_metadata(content, url, video_info)
        
        # Prepare basic article data
        article_data = {
            'url': url,
            'title': title,
            'content': formatted_content,
            'source': 'subtitle-processor',
            'should_clean_html': False,
            'location': location
        }
        
        # Add tags if provided
        if tags:
            article_data['tags'] = tags
        
        # Add explicit author if provided (overrides video_info)
        if author:
            article_data['author'] = author
        
        # Add explicit published_date if provided (overrides video_info)
        if published_date:
            article_data['published_date'] = published_date
        
        # Add metadata from video info (only if not already set by explicit params)
        if video_info:
            # Add author/uploader (only if not explicitly provided)
            if not author:
                uploader = video_info.get('uploader')
                if uploader:
                    article_data['author'] = uploader
            
            # Add publish date (only if not explicitly provided)
            if not published_date:
                upload_date = video_info.get('upload_date')
                if upload_date:
                    try:
                        # Convert YYYYMMDD to ISO format
                        if len(upload_date) == 8:
                            year = upload_date[:4]
                            month = upload_date[4:6]
                            day = upload_date[6:8]
                            video_published_date = f"{year}-{month}-{day}T00:00:00Z"
                            article_data['published_date'] = video_published_date
                    except:
                        pass
            
            # Add summary from description
            description = video_info.get('description', '')
            if description:
                # Limit summary length
                summary = description[:500] + '...' if len(description) > 500 else description
                article_data['summary'] = summary
        
        return article_data
    
    def _format_content_with_metadata(self, content: str, url: str, 
                                    video_info: Optional[Dict[str, Any]] = None) -> str:
        """Format content with metadata header."""
        
        # Start with metadata header
        formatted_parts = []
        
        # Add video information if available
        if video_info:
            metadata_lines = []
            
            uploader = video_info.get('uploader')
            if uploader:
                metadata_lines.append(f"**作者**: {uploader}")
            
            upload_date = video_info.get('upload_date')
            if upload_date:
                try:
                    # Format date nicely
                    if len(upload_date) == 8:
                        year = upload_date[:4]
                        month = upload_date[4:6]
                        day = upload_date[6:8]
                        formatted_date = f"{year}-{month}-{day}"
                        metadata_lines.append(f"**发布日期**: {formatted_date}")
                except:
                    pass
            
            duration = video_info.get('duration')
            if duration:
                # Convert duration to human readable format
                hours = duration // 3600
                minutes = (duration % 3600) // 60
                seconds = duration % 60
                
                if hours > 0:
                    duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = f"{minutes}:{seconds:02d}"
                
                metadata_lines.append(f"**时长**: {duration_str}")
            
            view_count = video_info.get('view_count')
            if view_count:
                metadata_lines.append(f"**观看次数**: {view_count:,}")
            
            if metadata_lines:
                formatted_parts.append("**视频信息**")
                formatted_parts.extend(metadata_lines)
                formatted_parts.append("")  # Empty line
        
        # Add source URL
        formatted_parts.append(f"**原视频链接**: {url}")
        formatted_parts.append("")  # Empty line
        
        # Add separator
        formatted_parts.append("---")
        formatted_parts.append("")  # Empty line
        
        # Add main content
        formatted_parts.append("**转录内容**")
        formatted_parts.append("")  # Empty line
        formatted_parts.append(content)
        
        return "\n".join(formatted_parts)
    
    def _save_single_article(self, article_data: Dict[str, Any]) -> bool:
        """Save a single article to Readwise."""
        try:
            logger.info(f"正在发送文章到Readwise API: {article_data.get('title')}")
            logger.info(f"API URL: {self.api_base_url}/save/")
            
            headers = {
                'Authorization': f'Token {self.api_token}',
                'Content-Type': 'application/json'
            }
            
            # Log article data (excluding full content for brevity)
            log_data = {k: v for k, v in article_data.items() if k != 'content'}
            log_data['content_length'] = len(article_data.get('content', ''))
            logger.info(f"发送的数据: {log_data}")
            
            response = requests.post(
                f'{self.api_base_url}/save/',
                json=article_data,
                headers=headers,
                timeout=30
            )
            
            logger.info(f"Readwise API响应状态码: {response.status_code}")
            
            if response.status_code in [200, 201]:
                logger.info("✅ 成功发送到Readwise!")
                result = response.json()
                logger.info(f"Readwise响应数据: {result}")
                if 'url' in result:
                    logger.info(f"📝 Readwise文章URL: {result['url']}")
                return True
            else:
                logger.error(f"❌ Readwise API错误: {response.status_code} {response.text}")
                try:
                    error_detail = response.json()
                    logger.error(f"错误详情: {error_detail}")
                except:
                    pass
                return False
                
        except requests.RequestException as e:
            logger.error(f"❌ Readwise请求失败: {str(e)}")
            logger.exception("详细错误信息:")
            return False
    
    def _save_long_content(self, content: str, title: str, url: str, 
                          video_info: Optional[Dict[str, Any]] = None,
                          published_date: Optional[str] = None,
                          author: Optional[str] = None,
                          location: str = 'new',
                          tags: Optional[List[str]] = None,
                          language: Optional[str] = None) -> bool:
        """Save long content by splitting into multiple articles."""
        try:
            # Split content into chunks
            chunks = self._split_content_into_chunks(content, self.max_content_length - 2000)  # Leave room for metadata
            
            logger.info(f"Splitting content into {len(chunks)} parts")
            
            success_count = 0
            for i, chunk in enumerate(chunks, 1):
                chunk_title = f"{title} (Part {i}/{len(chunks)})"
                
                # Prepare article data for this chunk
                article_data = self._prepare_article_data(chunk, chunk_title, url, video_info,
                                                        published_date, author, location, tags, language)
                
                # Add part information to content
                part_header = f"**第 {i} 部分 (共 {len(chunks)} 部分)**\n\n"
                article_data['content'] = part_header + article_data['content']
                
                if self._save_single_article(article_data):
                    success_count += 1
                    logger.info(f"Saved part {i}/{len(chunks)}")
                else:
                    logger.error(f"Failed to save part {i}/{len(chunks)}")
            
            if success_count > 0:
                logger.info(f"Saved {success_count}/{len(chunks)} parts to Readwise")
                return True
            else:
                logger.error("Failed to save any parts to Readwise")
                return False
                
        except Exception as e:
            logger.error(f"Error saving long content: {str(e)}")
            return False
    
    def _split_content_into_chunks(self, content: str, max_chunk_size: int) -> list[str]:
        """Split content into smaller chunks."""
        if len(content) <= max_chunk_size:
            return [content]
        
        chunks = []
        
        # Try to split by paragraphs first
        paragraphs = content.split('\n\n')
        current_chunk = []
        current_size = 0
        
        for paragraph in paragraphs:
            paragraph_size = len(paragraph)
            
            # If single paragraph is too large, split it
            if paragraph_size > max_chunk_size:
                # Add current chunk if it has content
                if current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                    current_chunk = []
                    current_size = 0
                
                # Split large paragraph by sentences
                sentence_chunks = self._split_paragraph_by_sentences(paragraph, max_chunk_size)
                chunks.extend(sentence_chunks)
                continue
            
            # If adding this paragraph would exceed limit, start new chunk
            if current_size + paragraph_size > max_chunk_size and current_chunk:
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [paragraph]
                current_size = paragraph_size
            else:
                current_chunk.append(paragraph)
                current_size += paragraph_size + 2  # Add 2 for \n\n
        
        # Add remaining chunk
        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))
        
        return chunks
    
    def _split_paragraph_by_sentences(self, paragraph: str, max_size: int) -> list[str]:
        """Split a large paragraph into smaller chunks by sentences."""
        import re
        
        # Split by sentence endings
        sentences = re.split(r'([.!?。！？]+)', paragraph)
        
        chunks = []
        current_chunk = []
        current_size = 0
        
        i = 0
        while i < len(sentences):
            sentence = sentences[i]
            
            # If this is a punctuation mark, combine with previous sentence
            if i > 0 and sentence.strip() in '.!?。！？':
                if current_chunk:
                    current_chunk[-1] += sentence
                    current_size += len(sentence)
                i += 1
                continue
            
            sentence_size = len(sentence)
            
            # If single sentence is too large, split it arbitrarily
            if sentence_size > max_size:
                # Add current chunk if it has content
                if current_chunk:
                    chunks.append(''.join(current_chunk))
                    current_chunk = []
                    current_size = 0
                
                # Split large sentence into smaller parts
                words = sentence.split()
                word_chunk = []
                word_size = 0
                
                for word in words:
                    word_len = len(word) + 1  # +1 for space
                    if word_size + word_len > max_size and word_chunk:
                        chunks.append(' '.join(word_chunk))
                        word_chunk = [word]
                        word_size = len(word)
                    else:
                        word_chunk.append(word)
                        word_size += word_len
                
                if word_chunk:
                    chunks.append(' '.join(word_chunk))
                
                i += 1
                continue
            
            # If adding this sentence would exceed limit, start new chunk
            if current_size + sentence_size > max_size and current_chunk:
                chunks.append(''.join(current_chunk))
                current_chunk = [sentence]
                current_size = sentence_size
            else:
                current_chunk.append(sentence)
                current_size += sentence_size
            
            i += 1
        
        # Add remaining chunk
        if current_chunk:
            chunks.append(''.join(current_chunk))
        
        return chunks
    
    def test_connection(self) -> bool:
        """Test Readwise API connection."""
        if not self.is_configured():
            logger.error("Readwise not configured")
            return False
        
        try:
            headers = {
                'Authorization': f'Token {self.api_token}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f'{self.api_base_url}/auth/',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Readwise API connection successful")
                return True
            else:
                logger.error(f"Readwise API test failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Readwise connection test error: {str(e)}")
            return False