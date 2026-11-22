//
//  Created by bend on 27/11/09.
//  Copyright Firemint 2009. All rights reserved.
//

#if defined(PASS_THROUGH)

uniform lowp sampler2D s_Texture0;
varying highp vec2 v_TexCoord;

void main()
{
	highp vec3 s = texture2D(s_Texture0, v_TexCoord).rgb;
	gl_FragColor = vec4(s, 1.0);
}

#endif

#if defined(BLUR_HORIZONTAL) || defined(BLUR_VERTICAL)

uniform lowp sampler2D s_Texture0;
varying highp vec2 v_TexCoord;
uniform highp float u_PointSize; //inverse of texture dimensions

highp vec3 sampleTexture(lowp sampler2D sTextureImage, highp vec2 vTexCoord, highp float nOffset, highp float nWeight)
{
#if defined(BLUR_HORIZONTAL)
	highp vec3 vColor 	 = texture2D( sTextureImage, vTexCoord + vec2(nOffset, 0) ).rgb * nWeight;
	vColor 				+= texture2D( sTextureImage, vTexCoord - vec2(nOffset, 0) ).rgb * nWeight;
#elif defined(BLUR_VERTICAL)
	highp vec3 vColor 	 = texture2D( sTextureImage, vTexCoord + vec2(0, nOffset) ).rgb * nWeight;
	vColor 				+= texture2D( sTextureImage, vTexCoord - vec2(0, nOffset) ).rgb * nWeight;
#endif
	return vColor;
}

#if defined(BLUR_11)
const highp float w11	= 1.0			/ 1048576.0;
const highp float w10 	= 20.0			/ 1048576.0;
const highp float w9 	= 190.0			/ 1048576.0;
const highp float w8 	= 1140.0		/ 1048576.0;
const highp float w7 	= 4845.0		/ 1048576.0;
const highp float w6 	= 15504.0		/ 1048576.0;
const highp float w5 	= 38760.0		/ 1048576.0;
const highp float w4 	= 77520.0		/ 1048576.0;
const highp float w3 	= 125970.0		/ 1048576.0;
const highp float w2 	= 167960.0		/ 1048576.0;
const highp float w1 	= 184756.0		/ 1048576.0;

void main()
{
	highp float ONE_PIXEL = u_PointSize;
	
	highp vec3 s = texture2D( s_Texture0, v_TexCoord  ).rgb * w1;
	highp float offset = ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w2);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w3);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w4);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w5);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w6);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w7);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w8);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w9);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w10);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w11);
	
	gl_FragColor = vec4(s, 1.0);
}
#endif
/*
#if defined(BLUR_9)
const highp float w9	= 1.0			/ 65536.0;
const highp float w8	= 16.0			/ 65536.0;
const highp float w7	= 120.0			/ 65536.0;
const highp float w6	= 560.0			/ 65536.0;
const highp float w5	= 1820.0		/ 65536.0;
const highp float w4	= 4368.0		/ 65536.0;
const highp float w3	= 8008.0		/ 65536.0;
const highp float w2	= 11440.0		/ 65536.0;
const highp float w1	= 12870.0		/ 65536.0;

void main()
{
	highp float ONE_PIXEL = u_PointSize;
	highp float offset = ONE_PIXEL;
	
	highp vec3 s = texture2D( s_Texture0, v_TexCoord  ).rgb * w1;
	
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w2);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w3);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w4);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w5);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w6);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w7);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w8);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w9);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w10);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w11);
	
	gl_FragColor = vec4(s, 1.0);
}
#endif
*/
#if defined(BLUR_7)
const highp float w7	= 1.0			/ 4096.0;
const highp float w6	= 12.0			/ 4096.0;
const highp float w5	= 66.0			/ 4096.0;
const highp float w4	= 220.0			/ 4096.0;
const highp float w3	= 495.0			/ 4096.0;
const highp float w2	= 792.0			/ 4096.0;
const highp float w1	= 924.0			/ 4096.0;

void main()
{
	highp float ONE_PIXEL = u_PointSize;

	highp vec3 s = texture2D( s_Texture0, v_TexCoord  ).rgb * w1;
	highp float offset = ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w2);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w3);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w4);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w5);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w6);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w7);
	
	gl_FragColor = vec4(s, 1.0);
}
#endif

#if defined(BLUR_5)
const highp float w5	= 1.0			/ 256.0;
const highp float w4	= 8.0			/ 256.0;
const highp float w3	= 28.0			/ 256.0;
const highp float w2	= 56.0			/ 256.0;
const highp float w1	= 70.0			/ 256.0;

void main()
{
	highp float ONE_PIXEL = u_PointSize;

	highp vec3 s = texture2D( s_Texture0, v_TexCoord  ).rgb * w1;
	highp float offset = ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w2);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w3);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w4);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w5);
	
	gl_FragColor = vec4(s, 1.0);
}
#endif

#if defined(BLUR_3)
const highp float w3	= 1.0			/ 16.0;
const highp float w2	= 4.0			/ 16.0;
const highp float w1	= 6.0			/ 16.0;

void main()
{
	highp float ONE_PIXEL = u_PointSize;

	highp vec3 s = texture2D( s_Texture0, v_TexCoord  ).rgb * w1;
	highp float offset = ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w2);
	offset += ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w3);
	
	gl_FragColor = vec4(s, 1.0);
}
#endif

#if defined(BLUR_2)
const highp float w2	= 1.0			/ 4.0;
const highp float w1	= 2.0			/ 4.0;

void main()
{
	highp float ONE_PIXEL = u_PointSize;

	highp vec3 s = texture2D( s_Texture0, v_TexCoord  ).rgb * w1;
	highp float offset = ONE_PIXEL;
	s += sampleTexture(s_Texture0, v_TexCoord, offset, w2);
	
	gl_FragColor = vec4(s, 1.0);
}
#endif

#endif
