/* SPDX-License-Identifier: GPL-3.0-or-later
 * Real VA picture crop (16,32) from 3840x2160 to 1920x1080, keys 0/2.
 * Build with libva-drm; run through livecd exec, passing NEW.h264 NEW.nv12.
 * The raw reference is the visible crop, not the padded allocation. */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <va/va.h>
#include <va/va_drm.h>
#include <va/va_enc_h264.h>
#define VA(call) do {VAStatus status=(call); if(status!=VA_STATUS_SUCCESS){fprintf(stderr,"line %d: %s: %s\n",__LINE__,#call,vaErrorStr(status));exit(1);}} while(0)
#define CHECK(test) do {if(!(test)){fprintf(stderr,"line %d: %s\n",__LINE__,#test);exit(1);}} while(0)
static uint8_t luma(unsigned x,unsigned y,unsigned frame)
{
 unsigned value=32+(x/32*13+frame%2*18)%170+(y/32%16)*7;
 return value>235?235:value;
}
int main(int argc,char **argv)
{
 CHECK(argc==3);
 FILE *encoded=fopen(argv[1],"wbx"),*reference=fopen(argv[2],"wbx");CHECK(encoded&&reference);
 int fd=open("/dev/dri/renderD128",O_RDWR|O_CLOEXEC);CHECK(fd>=0);
 VADisplay display=vaGetDisplayDRM(fd);CHECK(display);
 int major,minor;VA(vaInitialize(display,&major,&minor));
 fprintf(stderr,"VA %d.%d: %s\n",major,minor,vaQueryVendorString(display));
 VAConfigAttrib attrs[]={{VAConfigAttribRTFormat,VA_RT_FORMAT_YUV420},
                        {VAConfigAttribRateControl,VA_RC_CBR},
                        {VAConfigAttribEncPackedHeaders,0}};
 VAConfigID config;VA(vaCreateConfig(display,VAProfileH264High,VAEntrypointEncSlice,
                                    attrs,sizeof(attrs)/sizeof(attrs[0]),&config));
 VASurfaceAttrib attr={.type=VASurfaceAttribPixelFormat,.flags=VA_SURFACE_ATTRIB_SETTABLE,
                      .value={.type=VAGenericValueTypeInteger,.value.i=VA_FOURCC_NV12}};
 VASurfaceID surfaces[3];VA(vaCreateSurfaces(display,VA_RT_FORMAT_YUV420,3840,2160,surfaces,3,&attr,1));
 VASurfaceID surface=surfaces[0];
 VAContextID context;VA(vaCreateContext(display,config,3840,2160,VA_PROGRESSIVE,surfaces,3,&context));
 VAImageFormat image_format={.fourcc=VA_FOURCC_NV12,.byte_order=VA_LSB_FIRST,.bits_per_pixel=12};
 VAImage image;VA(vaCreateImage(display,&image_format,3840,2160,&image));
 for(unsigned frame=0;frame<4;frame++) {
  uint8_t *data=NULL;VA(vaMapBuffer(display,image.buf,(void **)&data));CHECK(data&&image.num_planes==2);
  for(unsigned y=0;y<2160;y++)for(unsigned x=0;x<3840;x++)
   data[image.offsets[0]+y*image.pitches[0]+x]=luma(x,y,frame);
  for(unsigned y=0;y<1080;y++)for(unsigned x=0;x<3840;x+=2) {
   data[image.offsets[1]+y*image.pitches[1]+x]=70+frame%2*40;
   data[image.offsets[1]+y*image.pitches[1]+x+1]=170-frame%2*30;
  }
  VA(vaUnmapBuffer(display,image.buf));
  VA(vaPutImage(display,surface,image.image_id,0,0,3840,2160,0,0,3840,2160));
  for(unsigned y=32;y<32+1080;y++)for(unsigned x=16;x<16+1920;x++)fputc(luma(x,y,frame),reference);
  for(unsigned y=0;y<1080/2;y++)for(unsigned x=0;x<1920;x+=2) {
   fputc(70+frame%2*40,reference);fputc(170-frame%2*30,reference);
  }
  VABufferID coded;VA(vaCreateBuffer(display,context,VAEncCodedBufferType,8*1024*1024,1,NULL,&coded));
  VAEncSequenceParameterBufferH264 sequence={0};
  sequence.level_idc=52;sequence.intra_period=2;sequence.intra_idr_period=2;
  sequence.ip_period=1;sequence.bits_per_second=40000000;sequence.max_num_ref_frames=1;
  sequence.picture_width_in_mbs=240;sequence.picture_height_in_mbs=135;
  sequence.seq_fields.bits.chroma_format_idc=1;sequence.seq_fields.bits.frame_mbs_only_flag=1;
  sequence.seq_fields.bits.direct_8x8_inference_flag=1;
  sequence.seq_fields.bits.log2_max_frame_num_minus4=4;
  sequence.seq_fields.bits.log2_max_pic_order_cnt_lsb_minus4=4;
  sequence.vui_parameters_present_flag=1;sequence.vui_fields.bits.timing_info_present_flag=1;
  sequence.vui_fields.bits.fixed_frame_rate_flag=1;sequence.num_units_in_tick=1;sequence.time_scale=120;
  sequence.frame_cropping_flag=1;sequence.frame_crop_left_offset=8;
  sequence.frame_crop_right_offset=(3840-16-1920)/2;
  sequence.frame_crop_top_offset=16;sequence.frame_crop_bottom_offset=(2160-32-1080)/2;
  VAEncPictureParameterBufferH264 picture={0};
  picture.CurrPic.picture_id=surfaces[1+frame%2];picture.CurrPic.frame_idx=frame%2;
  picture.CurrPic.flags=VA_PICTURE_H264_SHORT_TERM_REFERENCE;
  picture.CurrPic.TopFieldOrderCnt=picture.CurrPic.BottomFieldOrderCnt=frame%2*2;
  for(unsigned i=0;i<16;i++) {picture.ReferenceFrames[i].picture_id=VA_INVALID_SURFACE;picture.ReferenceFrames[i].flags=VA_PICTURE_H264_INVALID;}
  if(frame%2){picture.ReferenceFrames[0]=picture.CurrPic;picture.ReferenceFrames[0].picture_id=surfaces[1];picture.ReferenceFrames[0].frame_idx=0;}
  picture.coded_buf=coded;picture.frame_num=frame%2;picture.pic_init_qp=26;
  picture.pic_fields.bits.idr_pic_flag=!(frame%2);picture.pic_fields.bits.reference_pic_flag=1;
  picture.pic_fields.bits.entropy_coding_mode_flag=1;picture.pic_fields.bits.deblocking_filter_control_present_flag=1;
  VAEncSliceParameterBufferH264 slice={0};
  slice.num_macroblocks=240*135;slice.slice_type=frame%2?0:2;slice.idr_pic_id=frame/2;
  slice.pic_order_cnt_lsb=frame%2*2;
  for(unsigned i=0;i<32;i++) {
   slice.RefPicList0[i].picture_id=slice.RefPicList1[i].picture_id=VA_INVALID_SURFACE;
   slice.RefPicList0[i].flags=slice.RefPicList1[i].flags=VA_PICTURE_H264_INVALID;
  }
  if(frame%2)slice.RefPicList0[0]=picture.ReferenceFrames[0];
  VABufferID buffers[3];
  VA(vaCreateBuffer(display,context,VAEncSequenceParameterBufferType,sizeof(sequence),1,&sequence,&buffers[0]));
  VA(vaCreateBuffer(display,context,VAEncPictureParameterBufferType,sizeof(picture),1,&picture,&buffers[1]));
  VA(vaCreateBuffer(display,context,VAEncSliceParameterBufferType,sizeof(slice),1,&slice,&buffers[2]));
  VA(vaBeginPicture(display,context,surface));VA(vaRenderPicture(display,context,buffers,3));VA(vaEndPicture(display,context));
  VA(vaSyncSurface(display,surface));
  VACodedBufferSegment *segment=NULL;VA(vaMapBuffer(display,coded,(void **)&segment));
  size_t total=0;for(;segment;segment=segment->next){CHECK(segment->buf&&segment->size);CHECK(fwrite(segment->buf,1,segment->size,encoded)==segment->size);total+=segment->size;}
  VA(vaUnmapBuffer(display,coded));CHECK(total);
  for(unsigned i=0;i<3;i++)VA(vaDestroyBuffer(display,buffers[i]));
  VA(vaDestroyBuffer(display,coded));fprintf(stderr,"frame %u: %zu coded bytes\n",frame,total);
 }
 CHECK(!fclose(encoded)&&!fclose(reference));
 VA(vaDestroyImage(display,image.image_id));VA(vaDestroyContext(display,context));
 VA(vaDestroySurfaces(display,surfaces,3));VA(vaDestroyConfig(display,config));VA(vaTerminate(display));close(fd);
 return 0;
}
